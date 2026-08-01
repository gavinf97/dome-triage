# PREPROCESSING.md — NLP text preprocessing across the pipeline, explained and justified

Every technique on this page was checked directly against the running code and, where noted,
against a live interpreter inside the actual Docker image — nothing here is inferred from
docstrings alone. Where a choice has a real, live consequence (good or bad), that consequence is
stated plainly, not smoothed over. Where something wasn't fixed, the reason it wasn't is given —
not a justification written after the fact, but the actual tradeoff.

**Scope**: this page covers text-content preprocessing (what happens to titles/abstracts before
they're matched, scored, or embedded). It does **not** cover ID normalization (DOI/PMID/PMCID
string cleanup for deduplication, `src/dome_triage/ingest/id_mapping.py`) — that's a different
concern (record identity, not language), unrelated to anything below.

Cross-linked from `STEPS_Progress.md` at every step that actually applies one of these techniques,
rather than duplicated inline there — this file is the one place to look for "why does the text
get treated this way," `STEPS_Progress.md` stays the step-by-step runbook.

---

## Where preprocessing happens — one map

| Consumer | Function(s) called | Depth |
|---|---|---|
| `WeightedSumScorer` (scoring, Steps 11–12) | none — raw `.lower()` substring match | lightest |
| `Bm25Scorer` (scoring, Steps 11–12) | `clean_text()` — full pipeline | heaviest |
| `TfidfCosineScorer` (scoring, Steps 11–12) | `clean_text()` — full pipeline | heaviest |
| TF-IDF term extraction (`tfidf_extract.py`, Steps 4/6) | `clean_text()` + a second sklearn stopword pass | heaviest, plus extra |
| KeyBERT extraction (`keybert_extract.py`, Step 5) | `strip_html_tags()` only | lightest of the extraction pair |

The rest of this page explains each row.

---

## The core function: `clean_text()` (`src/dome_triage/keywords/preprocess.py`)

Applied, in this exact order, to every string it touches:

1. **Strip HTML tags** — `re.sub(r"<[^>]+>", " ", text)`. Not a defensive guess: an earlier
   extraction pass (`categorized_terms.csv`, the predecessor MLit-Triage-Nextflow project) had
   `h4`/`background`/`http` polluting its top TF-IDF terms, because real EPMC abstracts do contain
   literal pseudo-HTML like `<h4>Background</h4>`. This fix is a direct response to that observed
   failure, not a hypothetical.
2. **Strip non-alpha characters, except hyphens and whitespace** — `re.sub(r"[^a-zA-Z\s-]", " ",
   text)`. Hyphens are deliberately preserved so compound terms don't get torn apart. Live-verified:
   `t-SNE` → `t-sne`, `single-cell` → `single-cell`, `multi-omics` → `multi-omics`,
   `state-of-the-art model` → `state-of-the-art model` — all survive as single tokens. These are
   real, current lexicon terms (Step 8c), so this isn't a hypothetical either.
3. **Tokenize + lowercase** — `word_tokenize(text.lower())` (NLTK's Penn-Treebank-style tokenizer,
   not a plain `.split()` — handles punctuation-adjacent boundaries like `papers,` more sensibly).
4. **Drop stopwords** — NLTK's built-in English list (~179 words: "the", "and", "of", "with", ...)
   plus any `extra_stopwords` the caller passes. Only `tfidf_extract.py` actually passes any (from
   `configs/tfidf.yaml`); `scoring.py` never does, so every scorer's preprocessing uses the plain
   NLTK list with no extras.
5. **Drop tokens of length ≤ 2** — `len(token) > 2`. Sweeps out orphaned single/double letters.
   **Live-verified side effect**: this also empties out any 2-character *lexicon* term run through
   the same function — `clean_text('AI')` → `''`, `clean_text('ML')` → `''`. Checked directly:
   today's production lexicon (`keyword_lexicon.csv`, `keyword_lexicon_exclusionary.csv`) has
   **zero** 1–2 character terms, so this isn't live-biting anything right now. It's a landmine for
   later, though: if a future curation round adds a bare `ai`/`ml`/`nn` as a standalone unigram
   term, `Bm25Scorer`/`TfidfCosineScorer` will silently score against nothing for that term (it
   vanishes before either scorer ever sees it), while `WeightedSumScorer` — which never calls
   `clean_text()` — would still match it fine via raw substring search. Worth a manual check
   before adding any new 1–2 character term.
6. **Lemmatize** — NLTK's `WordNetLemmatizer`, called with its default part-of-speech assumption
   (noun). Live-verified: correctly reduces regular plural nouns (`networks`→`network`,
   `models`→`model`, `algorithms`→`algorithm`, `performances`→`performance`) but leaves verb
   inflections untouched (`predicting`, `outperformed`, `classifying` all pass through unchanged) —
   because it's never told which words are verbs, and its default guess is always "treat as noun."
   **This is an accepted, not-fixed limitation**: most lexicon terms are noun phrases (`random
   forest`, `neural network`), not verbs, so a full POS-tagging pass wasn't judged worth the added
   complexity. If a future curation round leans on verb-form terms, this is why they won't unify
   with their inflections the way plural nouns do.

**Worked example** (live-verified): `"area under the curve"` → `"area curve"` — `under`/`the`
dropped as stopwords, everything else already lowercase/singular/>2 chars, so nothing further
changes.

---

## Who calls this, and how much of it — with the reasoning

| Consumer | Preprocessing applied | Why this specific depth |
|---|---|---|
| `WeightedSumScorer` | **None.** Raw `.lower()` substring match only (`_find_matched_terms`). | Deliberately bypasses `clean_text()` entirely. This is the one scorer built to respect literal phrase adjacency — "random forest" must appear as written. Routing it through tokenization/stopword-removal/lemmatization would destroy the exact phrase structure it exists to preserve. |
| `Bm25Scorer` | Full `clean_text()`, on both the corpus documents and the lexicon "pseudo-query" — positive and negative lexicons treated identically. | `rank_bm25`'s `BM25Okapi` does zero normalization of its own — it takes pre-tokenized lists and nothing else. Without upstream normalization, "Neural" in a title and "neural" in the lexicon would count as different tokens. Because BM25 already discards phrase structure by design (see below), there's no additional cost to running the full pipeline first. |
| `TfidfCosineScorer` | Full `clean_text()`, same as BM25. | Same reasoning. `TfidfVectorizer()` here is called with no `stop_words`/`ngram_range` override — it does no meaningful normalization of its own beyond its default whitespace-driven tokenizer; `clean_text()` does all the real work upstream. |
| TF-IDF term extraction (`tfidf_extract.py`, Steps 4/6) | Full `clean_text()`, **plus** a second, independent stopword pass from `TfidfVectorizer(stop_words="english")`. | Different job than scoring — this *discovers* candidate lexicon terms from the positive/baseline corpora, it doesn't score papers against an already-approved lexicon. `ngram_range=(1,3)` here (vs. scoring's implicit (1,1)) is what actually produces multi-word phrase candidates (`random forest`, `area under the curve`) that later get curated in Step 8. The second stopword pass (sklearn's own ~318-word list, not identical to NLTK's ~179-word list) layers on top of `clean_text()`'s — mostly redundant overlap, not a bug, just two off-the-shelf lists that don't fully subsume each other. |
| KeyBERT extraction (`keybert_extract.py`, Step 5) | `strip_html_tags()` only — no tokenization, stopword removal, or lemmatization. | Deliberate, not an oversight. `all-MiniLM-L6-v2` is a transformer sentence-embedding model — it derives meaning from natural word order and context, and stopwords carry real grammatical signal for a transformer even though they carry none for a bag-of-words counter. Lemmatizing/stripping stopwords before embedding would degrade the exact semantic signal the model relies on, so only the one confirmed real defect (literal HTML tags polluting terms) is fixed here, nothing else. |

---

## The recurring theme: phrase-flattening

`Bm25Scorer` and `TfidfCosineScorer` both eventually reduce every lexicon term — positive or
negative, single-word or multi-word — to independent unigram tokens before scoring anything:
BM25's query is built via `clean_text(" ".join(lexicon_terms)).split()`, and
`TfidfVectorizer()` defaults to `ngram_range=(1,1)`. "machine learning" is never looked for as the
phrase "machine learning" by either scorer — it becomes two separate, independently-scored pieces
of evidence, "machine" and "learning".

This single fact is the direct cause of two things documented elsewhere:
- **`STEPS_Progress.md` Step 8d's "redundant unigram" cleanup rule** — a standalone unigram term
  contributes zero marginal signal beyond what its parent phrase already contributes once
  flattened, so it's dropped (unless explicitly protected).
- **`STEPS_Progress.md` Step 12's negative-lexicon/BM25 explainer** — the specific, current,
  real cross-token overlaps between the negative lexicon and approved positive phrases
  (`forest`/`random`/`neural`/`area`/`bayes`), and what that means for how the negative lexicon
  actually behaves in practice. See that section for the full mechanism, not repeated here.

`WeightedSumScorer` is the sole exception — it never flattens anything, because it never routes
through `clean_text()` + `.split()` at all.

---

## Known, accepted limitations (not fixed, by choice — listed for retrospective review)

- **2-character lexicon terms silently vanish for BM25/TF-IDF-cosine** (not for weighted-sum).
  Not live-biting today (verified: zero 1–2 char terms in either production lexicon file) — check
  before adding one.
- **Lemmatization is noun-only.** Verb-form lexicon terms won't unify with their inflections.
  Not live-biting today (verified: no verb-form lexicon terms currently exist) — worth knowing if
  one gets added later.
- **TF-IDF term extraction double-applies stopword removal** (NLTK's list via `clean_text()`, then
  sklearn's own list via `TfidfVectorizer(stop_words="english")`). Redundant, not harmful — the two
  lists mostly overlap, so this doesn't remove anything it shouldn't, it's just not a clean single
  pass.
- **The `matched_terms__<scorer>` column shown to curators is not computed the same way as the
  score.** For every scorer, `matched_terms` comes from literal substring search on the *raw,
  uncleaned* text; for BM25/TF-IDF-cosine, the actual numeric `match_score` comes from the
  flattened/lemmatized/stopword-stripped token bag described above. They usually agree in spirit
  but are genuinely two different code paths — don't infer how the score was computed from what's
  displayed in `matched_terms`.
