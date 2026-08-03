# METHODS_REVIEW.md — scientific audit of the approach so far, and the model plan

**Status:** review and plan only. **Nothing in the codebase was changed to produce this document.**
Every number below was measured against the live repo and real data on 2026-08-02 (or fetched live
from the Europe PMC API on that date), not inferred from docstrings. Where the project already
documents an issue, that is credited explicitly rather than re-presented as a discovery — the point
here is to add what *isn't* yet known, not to restate `PREPROCESSING.md`.

Read this alongside, not instead of:
- [`ROADMAP.md`](ROADMAP.md) — phase plan and the existing Model Evaluation Standards
- [`STEPS_Progress.md`](STEPS_Progress.md) — the step-by-step runbook and decision log
- [`PREPROCESSING.md`](PREPROCESSING.md) — text-handling reference (already strong; extended here)
- [`curation_criteria/CRITERIA.md`](curation_criteria/CRITERIA.md) — the labeling rulebook

---

## 0. How to read this

The pipeline that exists is, on the whole, unusually well-engineered for a research codebase:
provenance ledger, human-never-bypassed rule, a genuine two-condition bake-off, an explicit Youden
operating point rather than an arbitrary cutoff, and a self-documenting habit that caught several
of its own defects before I looked. That is the baseline this review assumes. Section 9 lists what
should not be touched.

The criticisms below are therefore not "this is bad." They are: **the keyword/BM25 stage has
reached the end of what it can do, its measured quality is optimistically biased, and three
specific dataset properties will actively mislead a BERT fine-tune if carried into training
unchanged.** Those are fixable, and mostly cheap to fix.

Severity labels used throughout:
- **P0** — affects decisions you are about to make (curation, Step 14), fix before proceeding
- **P1** — affects the validity of reported results, fix before training
- **P2** — affects final model quality, address during the modelling phase
- **P3** — worth knowing, not urgent

---

## 1. State of play — verified numbers

| Quantity | Value | Source |
|---|---|---|
| Canonical dataset rows | 6,647 | `canonical_dataset.csv` |
| Definitively labeled (pos/neg) | 3,785 | 1,878 positive / 1,907 negative |
| — positives by provenance | 1,449 `human_curated` + 429 `registry_confirmed` | `label` × `label_confidence` |
| — negatives by provenance | 1,907 `human_curated` (single source family) | same |
| Skipped / conflict / unlabeled | 533 / 2 / 2,327 | same |
| Distinct journals (all / labeled) | 3,163 / 2,745 | ~1.4 labeled records per journal |
| Labeled year range (median) | 1940–2025 (2022) | pos median 2022, neg median 2022 |
| Positive lexicon | 296 terms (101 unigrams, 195 phrases) | `keyword_lexicon.csv` |
| Exclusionary lexicon | 18 terms | `keyword_lexicon_exclusionary.csv` |
| Bulk AI/ML pool (scored) | 744,647 | `bulk_candidates_scored.csv` |
| EPMC hits for the bulk query (2000–2026) | 827,912 | live API, 2026-08-02 |
| Current curation queue | 2,328 | `stratified_candidate_pool.csv` |
| Best bake-off AUROC | 0.797 (tfidf-cosine + exclusionary) | `scoring_bakeoff_report.csv` |
| Promoted scorer | bm25 + exclusionary, AUROC 0.774, threshold 107.597 | Step 11 decision log |

---

## 2. Executive summary — the findings that matter, ranked

1. **The bake-off is circular** (P1). The lexicon is derived from the same 3,785 labeled records
   the bake-off then scores. AUROC 0.774 is an in-sample number; the honest held-out figure is
   unknown and will be lower. The Youden threshold (107.597) was also selected on that same data
   and then applied to all 744,647 bulk records. There is currently **no unbiased estimate of the
   incumbent system's quality at all**. §7

2. **BM25's effective term weights were never chosen by anyone** (P1). Because the pseudo-query is
   `" ".join(296 terms).split()`, a token's weight equals *how many curated phrases happen to
   contain it*. Measured: `model`=41, `learning`=27, `machine`=22, `based`=10, `using`=9. The
   single highest-weighted token in an AI/ML relevance query is **`model`** — a word that also
   means mouse model, animal model, disease model, statistical model. §5

3. **Three dataset properties will teach a BERT the wrong function** (P0/P1). Top-10 journals are
   ~100% single-class (BMC Bioinformatics 14 pos / 0 neg; Bioinformatics 10/0; PLoS Comput Biol
   11/0; Nat Commun 11/0). All 428 abstract-less records are positive, zero are negative — a
   perfect separator, almost exactly the 429 `registry_confirmed` rows. Positive and negative
   classes come from different source families. `ROADMAP.md` currently specifies training on
   "title+abstract+**journal**+year+metadata", which would hand the model the shortcut. §8

4. **The retrieval query caps recall at ~78% before any model runs** (P1). `AI_ML_QUERY` is two
   phrases. Live EPMC count: **238,038 records** (2000–2026) contain "deep learning", "neural
   network", "random forest", "supervised learning", "large language model" or "convolutional
   neural network" but *neither* "artificial intelligence" *nor* "machine learning". They are
   invisible to the whole pipeline. §3

5. **Part of the exclusionary lexicon does the opposite of its stated purpose** (P2). Known and
   documented in Step 12 for 5 terms; quantified here for the first time: `bayes` cancels to
   **exactly zero** net weight, and the documented rationale ("lets `forest` be down-weighted
   without losing `random forest`") cannot hold under unigram flattening — there is no phrase left
   to protect, and `random` is itself in the exclusion list. Separately, 16 of the 21 exclusionary
   tokens are publication-type words that EPMC already supplies as structured `pub_types` metadata.
   §6

6. **`clean_text()` deletes exactly the vocabulary a 2026 model-type tagger needs** (P2). Digits
   are stripped: `GPT-4`→`gpt-`, `ResNet50`→`resnet`, `AlphaFold2`→`alphafold`, `F1 score`→`score`,
   `R2`→`∅`, `3D`→`∅`. `PREPROCESSING.md` documents the ≤2-char rule and hyphen preservation but not
   digit loss. This is survivable for the current lexicon and *irrelevant to a BERT* (subword
   tokenizers have no such problem) — but it blocks the rich-tagging goal if tagging is attempted
   with lexicon methods. §4

7. **The label predicate may have silently changed** (P0). The 3,785 inherited labels encode
   "belongs in the DOME registry." `CRITERIA.md` defines positive as "applies an ML/AI method as
   genuine methodology." These are related but not identical predicates. Mixing them without
   measuring agreement produces exactly the contradictory boundary `CRITERIA.md` was written to
   prevent — but across the inherited data rather than within the new. §9

8. **Clear-negative contamination is low and the existing screen is well-designed** (P3, positive
   finding). Measured: of 14,294,114 records passing `EXCLUDE_QUERY` (2015–2025), 38,742 contain an
   explicit ML-algorithm phrase — **0.27%**. A 10,000-record sample would contain ~27 mislabeled
   positives; a 2,000-record merge ~5. Step 14b's screening exists precisely to catch these. This
   part of the design is sound. §10

---

## 3. Retrieval — the query sets a ceiling nothing downstream can raise

`bulk_match.py`:
```python
AI_ML_QUERY = '"artificial intelligence" OR "machine learning"'
```
`clear_negative_sampler.py`:
```python
EXCLUDE_QUERY = ('SRC:MED NOT ("artificial intelligence" OR "machine learning" '
                 'OR "deep learning" OR "neural network")')
```

Live EPMC counts, 2000-01-01 to 2026-12-31, fetched 2026-08-02:

| Query | Hits |
|---|---:|
| Current inclusion query (AI OR ML) | 827,912 |
| Other core ML phrases (DL, NN, RF, supervised learning, LLM, CNN) | 563,487 |
| **Blind spot: other phrases NOT (AI OR ML)** | **238,038** |
| — "deep learning" without AI/ML | 93,633 |
| — "neural network" without AI/ML | 135,272 |
| — "random forest" without AI/ML | 34,379 |
| — "large language model" without AI/ML | 4,509 |
| Union of both | 1,065,950 |

**Three distinct problems.**

**(a) Recall ceiling.** 238,038 / 1,065,950 = **22.3% of the reachable AI/ML literature is outside
the pool entirely.** A paper reading "we trained a convolutional neural network to segment
histology images" and never writing "machine learning" cannot be found, ranked, sampled, curated,
or classified by anything built downstream. No classifier improvement recovers these; only the
query does.

**(b) The two queries are asymmetric.** Inclusion uses 2 phrases, exclusion negates 4. Papers
mentioning only "deep learning" or "neural network" are in neither pool — not a candidate, not a
clear negative. That is ~228,905 records (93,633 + 135,272) in a structural gap.

**(c) `SRC:MED` appears on the negative query only.** Positives are drawn from all of Europe PMC
(preprints, PMC, agricola, patents…); negatives from MEDLINE only. Source is therefore correlated
with label by construction. MEDLINE records differ systematically in abstract formatting, MeSH
completeness, and journal composition — all learnable shortcuts. This is a genuine confound, not a
theoretical one.

**Recommendations**
- **P1** Expand `AI_ML_QUERY` to a defensible phrase set (add at minimum: deep learning, neural
  network, random forest, supervised/unsupervised learning, support vector machine, gradient
  boosting, large language model, foundation model, transformer, computer vision, natural language
  processing, predictive model*, classifier). Measure the delta before committing; a widened query
  raises volume and lowers precision, and that trade should be a recorded decision like Step 11's.
- **P1** Make the two queries formal complements: `EXCLUDE_QUERY` must negate *exactly* the
  inclusion phrase set, no more and no less. Otherwise the gap persists at whatever the new size is.
- **P1** Drop `SRC:MED` from the negative query, or add it to the positive one. Either is defensible;
  the asymmetry is not.
- **P2** Treat *retrieval recall* as a reported metric with its own estimate. Concretely: take a
  random sample of ~300 EPMC records that a broad query returns, human-label whether each is
  AI/ML-methods, and estimate what fraction the production query captures. This is the only way to
  put a number on the ceiling instead of guessing.
- **P3** Note that a fine-tuned encoder scanning all of EPMC (Phase 7) does not need a phrase query
  at all. The long-term answer is that retrieval stops being lexical. Widening the query is a bridge,
  not a destination.

---

## 4. Preprocessing — extends `PREPROCESSING.md`, does not replace it

`PREPROCESSING.md` is accurate and already documents hyphen preservation, the ≤2-char rule (with the
correct live observation that `clean_text('AI')` → `''`), noun-only lemmatization, phrase flattening,
and the `matched_terms` / `match_score` code-path divergence. What follows is what it does not cover.

**Digit stripping.** `_NON_ALPHA_RE = re.compile(r"[^a-zA-Z\s-]")` removes every numeral. Live-verified
inside the image:

| Input | `clean_text()` output |
|---|---|
| `AI` | `''` |
| `ML` | `''` |
| `GPT-4` | `'gpt-'` |
| `ResNet50` | `'resnet'` |
| `AlphaFold2` | `'alphafold'` |
| `F1 score` | `'score'` |
| `R2` | `''` |
| `3D structure` | `'structure'` |
| `t-SNE` | `'t-sne'` ✓ |
| `scRNA-seq` | `'scrna-seq'` ✓ |
| `k-means` | `'k-means'` ✓ |
| `XGBoost`, `CNN`, `LSTM`, `SVM`, `BERT` | preserved ✓ |

Hyphenated and alphabetic terms survive cleanly, as documented. **Versioned model names do not.**
`GPT-4` and `GPT-3` collapse to the same `gpt-`; `ResNet50` and `ResNet101` both become `resnet`;
`AlphaFold2` and `AlphaFold3` both become `alphafold`. Evaluation vocabulary `F1` and `R2` vanish
entirely.

**Why this matters more now than before.** For the current binary lexicon task this is close to
harmless — the production lexicon contains no digit-bearing or ≤2-char terms (`PREPROCESSING.md`
verified this). But the goal has expanded to **rich tagging of model types**, and model types in
2026 are overwhelmingly versioned strings. Any attempt to build that tagger on `clean_text()` output
starts by deleting the distinctions it needs to make.

**The good news:** this is an argument *for* moving to a transformer, not a reason to rewrite
`clean_text()`. WordPiece/BPE tokenizers handle `GPT-4`, `ResNet50` and `AlphaFold3` natively. The
correct fix is to **stop routing model-facing text through `clean_text()` at all** — keep it for the
lexicon/TF-IDF discovery path where it belongs, and feed transformers raw (HTML-stripped) text.

**Recommendations**
- **P2** Do not extend `clean_text()` to preserve digits *for the transformer path* — bypass it
  entirely. Strip HTML, nothing else. (`keybert_extract.py` already does exactly this, for exactly
  this reason — follow that precedent.)
- **P3** If the lexicon path continues, add digit-bearing terms to `PROTECTED_UNIGRAMS`-style handling
  and note the limitation in `PREPROCESSING.md`'s "known limitations" list, which is the right home
  for it.

---

## 5. The lexicon → BM25 pipeline — the central methodological flaw

### 5.1 How the weights actually arise

`Bm25Scorer.score_corpus` builds its query as:
```python
query_tokens = clean_text(" ".join(lexicon_terms)).split()
scores = bm25.get_scores(query_tokens)
```
`rank_bm25`'s `BM25Okapi.get_scores` iterates the query list and *accumulates* per token:
```python
for q in query:
    score += self.idf.get(q) * (...)
```
Duplicates are not deduplicated. **A token appearing k times in the pseudo-query contributes k× its
BM25 term score.** Since the pseudo-query is the concatenation of all 296 curated terms, a token's
weight is precisely *the number of curated phrases containing it*.

Measured on the live lexicon: 296 terms → 543 query tokens → 225 distinct.

| Token | Weight (multiplicity) | Net after exclusionary |
|---|---:|---:|
| `model` | 41 | 41 |
| `learning` | 27 | 27 |
| `machine` | 22 | 22 |
| `neural` | 11 | 10 |
| `deep` | 11 | 11 |
| `based` | 10 | 10 |
| `curve` | 9 | 9 |
| `network` | 9 | 9 |
| `using` | 9 | 9 |
| `prediction` | 8 | 8 |
| `performance` | 8 | 8 |
| `accuracy` | 7 | 7 |
| `characteristic` | 7 | 7 |
| `forest` | 7 | 6 |
| `regression` | 7 | 7 |
| `auc` | 6 | 6 |
| `operating` | 6 | 6 |
| `classification` | 5 | 5 |
| `algorithm` | 5 | 5 |

### 5.2 Why this is a problem, concretely

**`model` is the highest-weighted token in the query, at 41.** In biomedical text `model` is one of
the least discriminative words available: *mouse model, animal model, model organism, disease model,
statistical model, 3D model, model system, modelling study*. Every one of those matches at maximum
weight. This is a precision leak sitting at the very top of the ranking function.

**Stopword-like tokens outrank method tokens.** `based` (10) and `using` (9) carry more weight than
`network` (9), `regression` (7), `classification` (5) and `algorithm` (5). They survive NLTK's
stopword list but carry no relevance signal whatsoever. They are there because phrases like
"deep-learning-based", "model-based", "using machine learning" were curated.

**Evaluation vocabulary is heavily weighted.** `curve` (9), `characteristic` (7), `operating` (6),
`auc` (6), `sensitivity` (6), `area` (4) — all from variants of "area under the receiver operating
characteristic curve". This makes any diagnostic-accuracy or clinical-prediction paper score highly
*whether or not it uses ML*. Given that the negative class is precisely "AI/ML-adjacent papers that
were rejected", this is likely a direct contributor to the modest 0.774 AUROC.

**Curation verbosity became weight.** `neural` has weight 11 because eleven phrases were curated
(`neural network`, `artificial neural network`, `deep neural network`, `neural network model`,
`neural network cnn`, `convolutional neural`, `deep convolutional neural`, …). A curator adding a
phrase variant was, unknowingly, incrementing a weight. Nobody made a weighting decision; the
weights are an artifact of how thoroughly each concept was enumerated.

**A note on Step 8d's "redundant unigram" rule.** `PREPROCESSING.md` states a standalone unigram
"contributes zero marginal signal beyond what its parent phrase already contributes once flattened."
Under the multiplicity mechanism this is not quite right — a standalone `forest` alongside seven
`forest`-containing phrases contributes +1 of 8, not 0. The cleanup's *direction* was fine; its
stated rationale understated what was happening. Worth correcting in the doc, since the same
reasoning could justify further edits that aren't as harmless.

### 5.3 Recommendations

- **P1** If BM25 is retained for any future run, **deduplicate the query and attach explicit
  weights**. `rank_bm25` has no weighted-query API, but the equivalent is trivial: score each unique
  token once via `get_scores([tok])` and combine with chosen weights, or use the curated
  `discriminative_score` as the weight. The key property is that weights become a *recorded
  decision*, not an emergent artifact.
- **P1** Remove pure function words (`based`, `using`, `via`, `approach`) from the effective query.
- **P2** Consider whether `model`, `curve`, `characteristic`, `operating`, `area`, `performance`,
  `accuracy` belong in a *relevance* lexicon at all. They describe how results are reported, not what
  method was used.
- **P2** If phrase structure genuinely matters, `WeightedSumScorer` is the only scorer that preserves
  it (it never calls `clean_text()`), and it is currently the *worst* performer partly because of the
  weighting bug already found and fixed but **not yet re-run**. A post-fix re-run is cheap and would
  close an open question in the decision log.
- **P3** Honestly: the highest-value move is not to fix BM25 but to **retire it to a baseline**. Its
  role should become "the incumbent that the transformer must beat," measured properly on held-out
  data (§7). Effort spent perfecting the lexicon is effort not spent on the model that replaces it.

---

## 6. The exclusionary lexicon

Full contents (18 terms → 22 tokens, 21 distinct):

```
area  bayes  forest  neural  random          ← generic/ambiguous method words
perspective  commentary  editorial  opinion  viewpoint  case report
letter to the editor  narrative review  correspondence  news
systematic review  meta-analysis  survey     ← publication types
```

### 6.1 The five colliding tokens — already documented, now quantified

Step 12's explainer in `STEPS_Progress.md` already identifies `area`/`bayes`/`forest`/`neural`/`random`
as colliding with positive phrases and explicitly leaves the retain-or-unwind decision open. Credit
where due — that is exactly the right way to log an unresolved trade-off. What was not quantified:

| Exclusionary token | Positive weight | Exclusionary | **Net** |
|---|---:|---:|---:|
| `neural` | 11 | 1 | 10 |
| `forest` | 7 | 1 | 6 |
| `random` | 5 | 1 | 4 |
| `area` | 4 | 1 | 3 |
| **`bayes`** | **1** | **1** | **0** |

**`bayes` is cancelled to exactly zero.** A paper about naive Bayes classification receives no
BM25 contribution whatsoever from the word "bayes"; only `naive` survives. That is a complete,
silent deletion of one method's primary identifying token.

**The documented rationale cannot hold.** `ROADMAP.md` states the exclusionary lexicon "is what
actually lets a necessary-but-generic word (e.g. `forest`) get down-weighted without losing the
specific phrase (`random forest`) that still needs it." Under unigram flattening there is no phrase
to preserve — `random forest` exists only as the tokens `random` and `forest`, *both of which are in
the exclusion list*. Down-weighting `forest` down-weights `random forest` by exactly the same amount.
The mechanism the rationale describes does not exist in this scorer. (It *does* exist in
`WeightedSumScorer`, which matches literal phrases — the Step 12 note already suggests scoping these
5 terms to that scorer, which is the correct instinct.)

**The counter-argument in the decision log** — that the exclusionary lexicon measurably helped BM25's
AUROC (0.767→0.774) net of this effect — is fair, but that +0.007 is (a) in-sample (§7), (b) untested
for significance, and (c) an aggregate that can easily hide "helped on 16 publication-type tokens,
hurt on 5 method tokens."

### 6.2 The sixteen publication-type tokens

These are the only tokens acting as clean negative evidence (they never appear in positive phrases):
`case, commentary, correspondence, editor, editorial, letter, meta-analysis, narrative, news, opinion,
perspective, report, review, survey, systematic, viewpoint`.

They are doing real work — but via the wrong mechanism. **Europe PMC already returns `pub_types` as
structured metadata, and `bulk_match.py` already captures it into the dataset.** Matching the *word*
"review" in free text is a lossy proxy for a field that states the article type authoritatively.

The text-matching approach also misfires on ordinary prose: "in the **case** of", "we **report**",
"**survey** data", "cases and controls", "**case**-control study" all trigger a penalty on papers
that may be entirely legitimate positives. `case` and `report` are especially common in clinical
abstracts.

### 6.3 Recommendations

- **P1** Replace the 16 publication-type tokens with a **structured filter on `pub_types`**. This is
  strictly more accurate, costs nothing at scoring time, and removes the prose false-positives. Keep
  the text terms only as a fallback for records with missing `pub_types`.
- **P2** Resolve the 5 colliding terms. Given §5, the cleanest resolution is to **drop them from the
  exclusionary lexicon and instead fix the positive side's weighting** — the problem they were trying
  to solve (generic words scoring too highly) is better solved by not giving those words weight 41
  in the first place.
- **P2** Whatever is decided, re-run the bake-off **on held-out data** and report a confidence
  interval on the delta. The current ±0.007 is not distinguishable from noise at n=3,785 without one.
- **P3** An 18-term exclusionary lexicon against a 296-term positive lexicon is very small. If the
  negative-evidence idea is kept, it deserves its own curation round — but only after §7's evaluation
  problem is fixed, otherwise there is no way to tell whether additions help.

---

## 7. Evaluation validity — the most important section

### 7.1 The circularity

The chain, verified in `pipeline/steps.py`:

```
step_keywords_tfidf         (L151-152)  positive_texts = labeled records where label == "positive"
                                        baseline_texts = labeled records where label == "negative"
                                              ↓
extract_tfidf_terms                     discriminative_score = tfidf_mean(pos) − tfidf_mean(neg)
                                              ↓
                                        human review picks terms, ranked by that score
                                              ↓
step_keywords_scoring_bakeoff (L423-426) evaluates on labeled records where
                                        label in ("positive","negative")   ← THE SAME 3,785 ROWS
```

The lexicon is a function of the evaluation set. Terms were selected *because* they separate these
specific positives from these specific negatives, then scored on their ability to separate those same
records. AUROC 0.774 is an **in-sample fit statistic, not a generalization estimate**.

Human review in the middle does not break the circularity — the candidate list a human chose from was
itself ranked by the target-derived score, and humans reviewed terms, not documents.

**Additionally, the operating threshold is double-dipped.** `_youden_optimal_threshold` picks the
cutoff maximising TPR−FPR *on the evaluation set*, and the resulting 107.597 was then applied to all
744,647 bulk records. Threshold selection on the test set is a textbook optimism source; the reported
accuracy 0.772 / precision 0.842 / recall 0.666 are all biased upward.

**None of this is documented.** `SCORING_BAKEOFF_RESULTS.md` contains no caveat about leakage,
in-sample fitting, or threshold selection. Given how carefully this project documents everything
else, I read this as genuinely unnoticed rather than glossed.

### 7.2 What the real number probably looks like

Unknown — that is the point. But two signals suggest the honest figure is meaningfully lower:
- 0.774 is *already* modest for a task where the classes are this distinguishable to a human.
- The negative class is composed of hard negatives (AI/ML-adjacent papers a curator rejected), which
  is a legitimately difficult contrast — but the lexicon was tuned specifically on those hard
  negatives, which is where the optimism concentrates.

There is also a **distribution-shift problem independent of leakage**: the bake-off's negatives are
*hard* negatives; deployment negatives (the 744,647-record pool, and eventually 40M EPMC records)
are dominated by *easy* negatives. A threshold tuned on a 50/50 hard-negative set has no principled
relationship to the operating point needed on a pool where true prevalence is low and most negatives
are trivial. The 273,927 records currently classified positive in the bulk pool (36.8%) should be
treated as an unvalidated number.

### 7.3 Recommendations — do these before anything else

- **P1** **Seal a test set now, before more curation.** Draw a stratified random ~15% of the 3,785
  labeled records, write it to `data/processed/dataset_splits.csv` (`ROADMAP.md` already specifies
  this file — it just doesn't exist yet), and never let any lexicon, threshold, or model touch it
  for tuning. Do this *before* the queue grows, so the split is defined on a stable population.
- **P1** **Re-derive the lexicon on train-only data and re-run the bake-off on the sealed test set.**
  This gives, for the first time, an unbiased estimate of the incumbent system — which is exactly the
  baseline the BERT must beat. Expect the number to drop; that drop is information, not failure.
- **P1** **Select the threshold on validation, report on test.** Never the same split.
- **P2** Report **bootstrap 95% CIs** on AUROC/AUPRC, and use **DeLong's test** for AUROC comparisons
  between scorers rather than eyeballing 0.774 vs 0.797. With n≈570 in a 15% test split, the CI will
  be wide (roughly ±0.04); knowing that is more useful than a false-precision point estimate.
- **P2** **Switch the headline metric from AUROC to AUPRC + recall-at-fixed-precision.** AUROC is
  prevalence-insensitive and will look flattering on a 50/50 evaluation set while saying almost
  nothing about performance at deployment prevalence. For a triage system the decision-relevant
  quantities are: *at 95% precision, what recall do we get?* and *what fraction of 40M records still
  needs human review?* The existing report's `precision_recall_at_quantiles` column is already
  gesturing at this — it should be promoted to the headline.
- **P2** **Re-run `weighted-sum` post-fix.** The decision log flags this as outstanding; it is cheap
  and closes a known gap.
- **P3** Add a leakage caveat to `SCORING_BAKEOFF_RESULTS.md` so the 0.774 figure is never quoted
  downstream as a generalization estimate.

---

## 8. Dataset composition — three confounds that would corrupt a fine-tune

These are the findings I would act on first, because they affect the training set you are actively
building right now.

### 8.1 Journal is a near-perfect shortcut

Top 10 journals among labeled records:

| Journal | negative | positive |
|---|---:|---:|
| BMC Bioinformatics | 0 | 14 |
| PLoS Comput Biol | 0 | 11 |
| Nat Commun | 0 | 11 |
| Bioinformatics | 0 | 10 |
| PLoS One | 0 | 10 |
| GigaScience | 0 | 9 |
| BMC Genomics | 0 | 8 |
| Comput Math Methods Med | 0 | 5 |
| Acute and critical care | 4 | 0 |
| JMIR dermatology | 2 | 2 |

Eight of the ten are 100% single-class. `ROADMAP.md`'s Model Evaluation Standards currently specify
training "primarily on title+abstract+**journal**+year+metadata". Supplying journal as a feature on
this data would let a model achieve strong validation numbers by learning a journal lookup table —
and then fail completely on the 3,163-journal long tail and on the 40M-record scan.

Note this is partly an artifact of *sparsity*, not bias: 3,785 records over 2,745 journals is ~1.4
records per journal, so most journals appear once and are trivially "100% one class". That makes it
worse, not better — the feature is almost pure memorization capacity.

- **P0** **Do not feed `journal` to the classifier.** Train on title+abstract text only for the
  primary model. If journal-as-feature is of interest, run it as a *separate ablation* and report the
  gap; a large gap is evidence of shortcut learning, not of a better model.
- **P0** **Split by journal group, not at random.** Use `GroupShuffleSplit`/`StratifiedGroupKFold`
  with `journal` as the group so the same journal never spans train and test. Otherwise even a
  text-only model leaks via journal-characteristic phrasing.
- **P1** Amend `ROADMAP.md`'s Model Evaluation Standards to reflect this. It is currently the one
  place where the specified protocol would actively cause harm.

### 8.2 Empty abstracts perfectly predict the positive class

| | positives | negatives |
|---|---:|---:|
| Records with no abstract | **428** | **0** |

428 of 1,878 positives (22.8%) have no abstract; not one negative lacks one. This aligns almost
exactly with the 429 `registry_confirmed` records — i.e. the DOME registry API dump supplies
positives without abstract text.

Two consequences:
1. **As a leak:** `len(abstract) == 0` is a 100%-precision positive detector on this data. Any model
   with access to that signal (including a transformer seeing an empty second segment) can exploit it.
2. **As a handicap on the current system:** those 428 records are scored by BM25 on title alone, which
   depresses their scores and manufactures false negatives — plausibly a real contributor to the 0.666
   recall figure.

- **P0** Decide explicitly. Options, in my order of preference: **(a)** fetch the missing abstracts
  from EPMC by PMID/DOI (`EpmcClient.get_by_ids` already exists — this is probably an afternoon's
  work and strictly the best outcome); **(b)** exclude abstract-less records from train/val/test and
  report them as a separate title-only evaluation slice; **(c)** keep them but add a `has_abstract`
  flag and verify via ablation that the model isn't using it.
- **P1** Whichever is chosen, record it in `CRITERIA.md`/`ROADMAP.md` — it is a dataset-definition
  decision, not an implementation detail.

### 8.3 Class provenance is confounded with class label

Positives = 1,449 `human_curated` + 429 `registry_confirmed`. Negatives = 1,907 `human_curated`, all
from the DOME_Top_Curate / Copilot-Data-Analysis family. The positive class contains a source the
negative class does not, and that source has systematically different text (no abstracts, §8.2), and
Step 14 will add a *third* provenance (`clear_negative_sampler`) that is negative-only and drawn from
a different EPMC subset (§3c).

By the time Step 14 merges, `source` will be strongly predictive of `label` — and source correlates
with formatting, metadata completeness, and journal mix, all of which are learnable.

- **P1** Add `source` to the ablation battery: train with and without source-correlated metadata,
  report the gap.
- **P1** Stratify splits by `label × source` so every source is represented on both sides of the split.
- **P2** When Step 14 runs, keep clear-negatives identifiable (`source_name` already does this) and
  **evaluate on hard negatives separately from easy negatives.** A model that only beats the baseline
  on easy negatives has not solved the triage problem — the hard-negative slice is the one that
  matters, and it must be reported separately or it will be diluted into invisibility.

---

## 9. Label semantics — resolve before curating 5,000 more papers

The 3,785 inherited labels answer: *does this paper belong in the DOME registry?* DOME's scope is
reporting standards for ML applied to life-science data — so a DOME-positive paper is one where the
D/O/M/E axes are meaningfully assessable.

`CRITERIA.md` defines positive as: *the paper applies an ML/AI method as a genuine part of its own
methodology.*

These overlap heavily but are not the same predicate. Cases where they diverge:
- An ML-methods paper in a non-life-science domain (pure CS, physics, engineering) — positive under
  `CRITERIA.md`, arguably out of scope for DOME.
- A life-science paper applying trivial logistic regression — positive under `CRITERIA.md`'s suggested
  default ("classical methods count: yes"), but a marginal DOME registry entry.
- A registry-confirmed entry where ML is central but the paper is a tool release — both agree, fine.

**Why it matters now.** You are about to add ~2,300–5,000 new labels under `CRITERIA.md`'s rule to
3,785 existing labels under the DOME-relevance rule. If the predicates differ even for 5–10% of
cases, the resulting training set contains contradictory examples straddling the boundary — which is
precisely the failure mode `CRITERIA.md` was written to prevent, just displaced from *within* the new
labels to *between* old and new.

**Recommendations**
- **P0** **Measure the disagreement.** Take a random 150–200 of the inherited labeled records, re-label
  them blind under `CRITERIA.md`, and compute Cohen's κ against the inherited label. This is perhaps
  three hours in the app you have already built, and it answers a question that otherwise contaminates
  every downstream number. Three outcomes:
  - κ > 0.8 → predicates are compatible, proceed, document the check.
  - κ 0.6–0.8 → usable but note it as a known label-noise floor; the model's ceiling is roughly this.
  - κ < 0.6 → the predicates genuinely differ; decide which one the project is answering and
    consider re-labeling the inherited set (or using it only for pretraining/weak supervision).
- **P0** **This double-labeling doubles as your human-agreement ceiling estimate**, which §12 needs
  anyway. Do it once, get both.
- **P1** State the chosen predicate in one sentence at the top of `CRITERIA.md`, and note explicitly
  whether inherited labels were produced under it.

---

## 10. What is working — do not rebuild these

Stated plainly because the rest of this document is critical, and a review that only criticises gives
a false picture of the codebase.

- **Provenance ledger** (`provenance.py`). Every artifact traceable to command, inputs, config, git
  commit. This is better than most published pipelines and should be preserved through the modelling
  phases.
- **The two-condition bake-off design.** Running each scorer with *and* without the exclusionary
  lexicon, as a deliberate before/after comparison rather than an assumption, is genuinely good
  experimental design. The circularity problem (§7) is orthogonal to this and does not diminish it.
- **Explicit Youden operating point**, reported with the threshold value, rather than an arbitrary
  cutoff. The mechanism is right; only the split discipline needs fixing.
- **`Undeterminable` as a first-class outcome**, excluded from training splits and retained as a
  calibration/routing validation set. This is a sophisticated design choice that most projects get
  wrong by forcing binary labels, and it will pay off directly in Phase 6.
- **Clear-negative screening (Step 14b).** Measured contamination is 0.27% (38,742 of 14,294,114
  records passing `EXCLUDE_QUERY` contain an explicit ML phrase — ~27 in a 10k sample, ~5 in a 2k
  merge). The screening step flags exactly these and never auto-rejects. This is well-designed and
  well-sized; do not over-engineer it.
- **Phased `--merge-limit`** to control class balance rather than dumping 10k negatives at once.
- **Human-never-bypassed rule** and conflict flagging rather than silent overwrite.
- **The curation app** after this session's work: ~0.27s per decision, keyboard-driven, criteria doc
  cross-linked. Annotation throughput is now a solved problem, which is why §12 argues for spending
  the savings on *better-chosen* examples rather than more of them.
- **`PREPROCESSING.md` itself.** The habit of writing down live-verified limitations, including
  unfixed ones with the reason they were not fixed, is the reason this review could be written
  quickly and precisely.

---

## 11. The model plan

### 11.1 Reframing the task

The current framing is one binary classifier. The stated goal is binary relevance **plus** rich
tagging of model types. I recommend treating this as **two heads on one encoder**, not two projects:

- **Head A — relevance.** Binary: does this paper apply/develop an AI/ML method on life-science data?
  This is the triage gate for the 40M-record scan.
- **Head B — DOME-aligned tagging.** Multi-label: which model family, learning paradigm, data
  modality, task type, and which DOME-reportable properties are present.

Shared encoder, two heads, joint loss. Rationale: the tagging labels are far sparser than the binary
label, and multi-task training lets the tagging head borrow representation from the much larger
binary signal. It also halves inference cost at scan time versus two separate models.

### 11.2 Ground the tagging schema in DOME, not in invention

This is the single highest-leverage design decision available, and the schema is already sitting in
`../dome-schema/releases/v2.0.0/`. DOME v2.0.0 represents **21 content fields (D1–D4, O1–O8, M1–M4,
E1–E5)** as structured objects. Several map directly onto what you want to tag:

| DOME v2 field | What a tagger would predict | Note |
|---|---|---|
| `optimization.algorithm.algName` | **model/algorithm type** | exactly the user's "model types within" |
| `optimization.algorithm.isNewAlg` | novel algorithm vs. applied existing | already a curation feature you trimmed |
| `optimization.encoding.encMeth` | feature encoding / representation | |
| `optimization.regularisation.regTechs` | regularization techniques used | array field |
| `optimization.meta.isMeta` / `metaMeths` | ensemble/meta-learning | |
| `data.provenance.source` | data source / modality | |
| `data.splits.numSplits` / `splitMeth` | whether splitting is described | strong DOME-compliance signal |
| `model.output.outType` | classification / regression / generation… | task type |
| `model.interpretability.interpType` | interpretability characterization | |
| `evaluation.measure.metrics` | which metrics reported | array field |
| `evaluation.comparison.cmpBase` | compared against a baseline? | |
| `evaluation.confidance.hasCI` / `isStatSig` | confidence intervals / significance | |

**Why this is the right choice:** it turns "rich tagging" from a nice-to-have into **automated
pre-population of DOME registry entries for curator confirmation**. The output is directly consumable
by the thing the project exists to serve, the label space is externally defined (so it is defensible
and not arbitrary), and it is a far stronger contribution than generic topic tags. It also gives the
tagging head a natural evaluation: agreement with human DOME annotations on the 429 registry-confirmed
entries you already hold.

**Practical scoping.** Do not attempt all 21 fields at once. Abstracts simply do not contain enough
information for most of them (licence, runtime, source-code availability are usually full-text or
metadata questions). Start with the subset genuinely inferable from title+abstract:

- **Tier 1 (abstract-inferable, start here):** `algName` (model family), `outType` (task type), data
  modality, learning paradigm, `metrics`, `isNewAlg`.
- **Tier 2 (often abstract-inferable):** `splitMeth` presence, `cmpBase`, `hasCI`.
- **Tier 3 (needs full text — defer):** everything about availability, licences, runtime, parameter
  counts.

Report per-field support and never report a metric for a field with too few positives to estimate.

### 11.3 A concrete model-family label set

For `algName`, a flat free-text field will not train. Propose a controlled vocabulary, hierarchical
so rare classes roll up:

```
linear/GLM              (linear regression, logistic regression, LASSO/ridge/elastic net)
tree-ensemble           (random forest, gradient boosting, XGBoost, LightGBM, decision tree)
kernel/SVM              (SVM, SVR, kernel methods, Gaussian process)
probabilistic/Bayesian  (naive Bayes, Bayesian networks, HMM, mixture models)
clustering              (k-means, hierarchical, DBSCAN, community detection)
dim-reduction           (PCA, t-SNE, UMAP, autoencoder-for-embedding)
classical-NN/MLP        (feedforward, perceptron, shallow ANN)
CNN                     (convolutional, ResNet, U-Net, VGG, EfficientNet)
RNN                     (LSTM, GRU, sequence-to-sequence)
transformer             (attention, BERT-family encoders, ViT)
LLM/foundation-model    (GPT-family, Llama, domain LLMs, prompt-based)
graph-NN                (GCN, GAT, message-passing)
generative              (GAN, VAE, diffusion, normalizing flows)
reinforcement-learning
other/unspecified
```

Multi-label (papers routinely use several), with `other/unspecified` as an explicit class rather than
an absence — "the abstract says ML but names no method" is common and worth capturing.

### 11.4 Encoder selection — run a bake-off, exactly as you did for scorers

**A caveat I want to be explicit about:** my knowledge has a cutoff of May 2026, and the encoder
landscape moves fast. Treat the list below as a *starting shortlist to verify at implementation
time*, not a settled ranking. The methodology — a bake-off under a fixed protocol, the same way Step
11 was run — matters more than the specific names, and is the part I would defend regardless.

**Recommended shortlist:**

| Model | Why | Rough size |
|---|---|---|
| **ModernBERT-base** | Best general modern encoder I'm aware of: 8,192-token context, RoPE, flash-attention, trained on far more data than original BERT. The long context matters — full abstracts never truncate, and title+abstract+MeSH fits comfortably. **My default recommendation for the primary model.** | ~149M |
| **PubMedBERT / BiomedBERT** (Microsoft) | Pretrained from scratch on PubMed abstracts — in-domain vocabulary, no general-English dilution. The strongest classic biomedical baseline and the natural domain comparator. | ~110M |
| **BioLinkBERT-base** | Pretraining uses document links (citations); strong on BLURB. Worth one run. | ~110M |
| **DeBERTa-v3-base** | Best-in-class general encoder for its size (disentangled attention, ELECTRA-style pretraining). Good control for "is domain pretraining actually helping?" | ~184M |
| **Bioformer-8L** | The ROADMAP's existing pick. 8 layers — genuinely fast. Its real role is the **production scan model**, where throughput over 40M records dominates. | ~43M |
| **SPECTER2 / scientific embeddings + linear probe** | Not a fine-tune: frozen document embeddings + logistic regression. Extremely cheap, often within a couple of points, and a superb sanity baseline. | — |

**Two things I would do that are not on most people's list:**

1. **Domain-adaptive pretraining (DAPT) on your own 744,647 abstracts.** You already have a large,
   perfectly in-domain, *unlabeled* corpus — the exact situation where continued MLM pretraining
   reliably helps (Gururangan et al., "Don't Stop Pretraining", ACL 2020). A few GPU-hours of
   continued MLM on ModernBERT-base over the bulk pool, before fine-tuning on 3,785 labels, is the
   highest expected-value compute you can spend. It costs no annotation.

2. **A cheap embedding+LR baseline before any fine-tune.** If frozen embeddings + logistic regression
   gets within ~2 points of a fine-tuned transformer (it often does at this data scale), that changes
   the deployment calculus entirely for the 40M scan.

**On LLMs (Phase 5).** Keep them, but scope them honestly. At 40M records an API-based LLM is
financially impossible under a £100 cap, and even local inference is slow. Their realistic role is:
(a) the **uncertain-confidence tier** only, per the existing routing design — which is already the
plan and is correct; (b) **weak supervision** to bootstrap the tagging labels (§12.3); (c) a
**zero/few-shot ceiling probe** on ~200 examples to see what's achievable without annotation. Do not
plan an LLM as the production triage model.

### 11.5 Training protocol specifics

- **Input**: `title + [SEP] + abstract`, raw text with HTML stripped, **never** `clean_text()` (§4).
  Consider appending MeSH headings as a third segment — you have them for 100% of labeled records,
  and they are curated vocabulary. Test as an ablation, not an assumption.
- **Exclude** `journal` and `year` from the primary model (§8.1). Ablate separately.
- **Class balance**: keep the mild negative skew the ROADMAP already argues for (~1.5–2.5:1) — the
  reasoning there is sound and matches deployment prevalence. Prefer **class weights + threshold
  tuning** over resampling; resampling discards data and distorts calibration.
- **Loss**: binary cross-entropy with label smoothing (~0.05) for Head A — smoothing is well-matched
  to a task with a known human-disagreement floor (§9). Per-label BCE with **per-label thresholds**
  for Head B.
- **Splits**: `StratifiedGroupKFold` grouped by journal, stratified by `label × source`. Sealed test
  set, defined once (§7.3).
- **Near-duplicate check**: `ROADMAP.md` already specifies this (preprint/published pairs). Do it with
  MinHash or embedding cosine over titles+abstracts, at the *cluster* level, before splitting.
- **Seeds**: ≥3 seeds, report mean ± sd. At n≈3,785 with a ~570-record test set, single-run
  differences of 1–2 points are noise. This is the most commonly skipped step and the most commonly
  regretted.
- **Early stopping** on validation AUPRC, not loss or accuracy.
- **Calibration**: **temperature scaling** on the validation set. `ROADMAP.md` currently specifies
  isotonic regression via `CalibratedClassifierCV` — that is a reasonable choice for sklearn models,
  but for neural network logits temperature scaling is the standard, needs one parameter (so it
  cannot overfit a small validation set the way isotonic can), and preserves ranking exactly. I'd
  suggest fitting both and picking on validation ECE.

### 11.6 Evaluation protocol — what to actually report

Per model, on the sealed test set:

- **AUPRC** (primary) and AUROC (secondary), each with bootstrap 95% CI.
- **Recall @ precision = 0.95** and **precision @ recall = 0.95** — the numbers that determine
  reviewer workload.
- **Calibration**: reliability diagram + ECE.
- **Slice metrics** — this is where the real insight lives:
  - hard negatives (curator-rejected AI/ML-adjacent) vs. easy negatives (clear-negative sampler)
  - with-abstract vs. title-only
  - by year bucket (does 2015 text behave like 2025 text?)
  - by `source`
- **Comparisons**: majority-class baseline; **the BM25 incumbent, honestly re-measured (§7.3)**;
  TF-IDF+LR; embeddings+LR; then transformers. McNemar's test for paired model comparisons; DeLong
  for AUROC pairs.
- **Human ceiling** from §9's κ study — report model performance *relative to* it. A model at 0.85
  when human self-agreement is 0.86 is finished; the same model against an assumed ceiling of 1.0
  looks like it needs more work.
- **`model_card.json`** per the existing Model Evaluation Standards (O1–O8, M1–M4, E1–E5). The
  ROADMAP already specifies this properly — self-applying DOME to your own models is a genuinely
  strong move and worth keeping prominent, since it is also a defensible thesis contribution.

---

## 12. Annotation strategy — spend the throughput gain on better examples

The curation app now runs at ~0.27s per decision. The bottleneck is your reading time, so the lever
is **which papers you read**, not how fast the app is.

### 12.1 Move from diversity sampling to uncertainty × diversity

The current stratified sampler is diversity-driven but **label-blind** — it maximises coverage of
score-band × journal × year cells regardless of how informative any given paper is. That is the right
choice for a cold start (which is what it was built for) and the wrong choice once a model exists.

Proposed sequence:
1. Curate the current 2,328 queue, or the first ~1,200–1,500 of it.
2. Train the first model (even a weak one).
3. For the next batch, rank the unlabeled pool by **predictive entropy** and sample within existing
   diversity strata. Uncertainty sampling typically yields 2–5× label efficiency on tasks like this.
4. Repeat every ~1,000 labels.

**Critical guard rail:** always keep a **purely random, never-active-selected** held-out slice.
Active learning biases the labeled distribution, and an actively-selected test set gives systematically
wrong estimates. Draw the sealed test set (§7.3) *before* any active learning begins.

### 12.2 Prioritize the blind spot

Once the retrieval query is widened (§3), deliberately over-sample the previously-invisible 238,038
records — "deep learning"/"neural network" papers that never say AI or ML. They are, by construction,
the region where the current system has zero evidence, and they are disproportionately likely to be
genuine positives.

### 12.3 Bootstrap the tagging labels with weak supervision

Hand-annotating ~5,000 papers × ~15 model-family labels is not realistic. Instead:
1. Write high-precision regex/dictionary labelling functions per model family (`\brandom forests?\b`,
   `\bXGBoost\b`, `\bU-?Net\b`, …). High precision, low recall, cheap.
2. Apply to the full labeled set to get noisy tags.
3. **Human-confirm in the app** rather than human-generate — confirming a proposed tag is perhaps 5×
   faster than recalling it unprompted. The app's feature-checklist mechanism already supports this
   pattern (`configs/curation_features.yaml` is explicitly a living list).
4. Optionally combine multiple noisy sources with a label model (Snorkel-style), though at this scale
   simple high-precision rules + confirmation will likely suffice.
5. An LLM few-shot tagger is a legitimate additional labelling function here — used to *propose*
   labels for human confirmation, never to produce silver labels consumed directly as truth.

### 12.4 Where the DOME registry itself helps

The 429 `registry_confirmed` records have **human DOME annotations already**. That is a small but
genuine gold set for Head B — the only place where tagging ground truth exists without new annotation
effort. Use it as a held-out evaluation set for the tagging head, and check whether `../EBI_Search_DOME`
or the registry API can supply more.

---

## 13. Deployment / scaling considerations (Phase 7)

- **Cascade, don't scan with the big model.** Stage 1: a cheap high-recall filter (widened lexical
  query, or Bioformer-8L/distilled ModernBERT at INT8) tuned for ~99% recall. Stage 2: the accurate
  model on whatever survives. Stage 3: LLM or human on the uncertain band. This is essentially the
  Phase 6 routing design extended upstream, and it is what makes 40M records tractable.
- **ONNX + INT8 quantization** for the production encoder; expect roughly 2–4× throughput over FP32
  CPU inference with minimal quality loss — but *measure* the quality delta on the sealed test set
  rather than assuming it is negligible.
- **Budget the scan explicitly before running it.** The 11h38m BM25 incident (documented in Step 12)
  is the precedent: at 40M records, a 10ms/record model is ~4.6 days of single-threaded compute.
  Estimate, then measure on 10k, then extrapolate, then run.
- **Version the model with the data.** `provenance.py` already does this for pipeline steps; extend
  the same discipline to model artifacts so a scored record can always be traced to the exact model
  version that scored it.

---

## 14. Prioritized action list

| # | Action | Severity | Effort | Section |
|---|---|---|---|---|
| 1 | Seal a stratified test set into `dataset_splits.csv` before more curation | **P0** | 1h | §7.3 |
| 2 | Double-label ~150–200 inherited records under `CRITERIA.md`; compute κ | **P0** | 3h | §9 |
| 3 | Decide + document handling of the 428 abstract-less positives (prefer: fetch them) | **P0** | 2–4h | §8.2 |
| 4 | Remove `journal` from planned model inputs; amend ROADMAP's Evaluation Standards | **P0** | 30m | §8.1 |
| 5 | Re-derive lexicon on train-only, re-run bake-off on sealed test → honest baseline | **P1** | 1 day | §7.3 |
| 6 | Widen `AI_ML_QUERY`; make `EXCLUDE_QUERY` its exact complement; fix `SRC:MED` asymmetry | **P1** | half day + refetch | §3 |
| 7 | Switch headline metric to AUPRC + R@P95; add bootstrap CIs | **P1** | half day | §7.3 |
| 8 | Group-aware (journal) splitting + near-duplicate clustering | **P1** | half day | §8.1 |
| 9 | Replace publication-type text terms with structured `pub_types` filter | **P1** | half day | §6.3 |
| 10 | Add leakage caveat to `SCORING_BAKEOFF_RESULTS.md` | **P1** | 15m | §7.3 |
| 11 | Deduplicate + explicitly weight the BM25 query if BM25 is run again | **P2** | half day | §5.3 |
| 12 | Resolve the 5 colliding exclusionary terms (recommend: drop) | **P2** | 1h | §6.3 |
| 13 | Re-run `weighted-sum` post-fix to close the open decision-log item | **P2** | 1h | §7.3 |
| 14 | Encoder bake-off under a fixed protocol (ModernBERT / PubMedBERT / DeBERTa / Bioformer / embed+LR) | **P2** | 1 week | §11.4 |
| 15 | DAPT on the 744k unlabeled abstracts | **P2** | GPU-hours | §11.4 |
| 16 | Define the DOME-aligned tagging schema; weak-supervision bootstrap | **P2** | 1 week | §11.2, §12.3 |
| 17 | Switch to uncertainty × diversity sampling after the first model | **P2** | 1 day | §12.1 |
| 18 | Bypass `clean_text()` for all transformer inputs | **P2** | 1h | §4 |
| 19 | Cascade + ONNX INT8 for the full scan | **P3** | Phase 7 | §13 |
| 20 | Note the multiplicity mechanism in `PREPROCESSING.md`'s Step 8d rationale | **P3** | 15m | §5.2 |

Items 1–4 are the ones I would genuinely do before curating another 1,000 papers. They are cheap, and
each one gets *more* expensive to fix the more labels accumulate under the current assumptions.

---

## 15. Open questions — these need your judgment, not mine

1. **Which predicate is the project answering** — "belongs in the DOME registry" or "applies an
   AI/ML method"? (§9) Everything downstream depends on this, and only you can decide it.
2. **Is non-life-science ML in or out?** `CRITERIA.md`'s `wrong-domain-non-bio` negative reason implies
   out; the stated goal "positive or negative for AI or ML papers" implies in.
3. **Is the tagging head a thesis contribution or a convenience feature?** If the former, the
   DOME-alignment argument (§11.2) is worth building the schema around properly. If the latter, a
   flat 15-class model-family tagger is enough.
4. **How much compute is genuinely available?** The £100 cap and "lab GPU first" framing shape whether
   DAPT and a 5-model bake-off are realistic. If GPU access is scarce, the embed+LR baseline becomes
   much more central.
5. **Do you want to re-fetch the bulk pool after widening the query?** It is another multi-hour EPMC
   fetch and would reset Step 12. Doing it *before* heavy curation is far cheaper than after.
6. **Should the 429 registry-confirmed positives be training data or held-out gold?** They are the only
   records with real DOME annotations (§12.4), which makes them unusually valuable as an evaluation set.

---

## 16. Summary in one paragraph

The engineering is strong and the provenance discipline is genuinely better than most published
pipelines. The scientific weak point is that **the only quality number the project has (AUROC 0.774)
is measured in-sample against a lexicon derived from the same records, with a threshold also chosen on
those records** — so the incumbent system's true performance is currently unknown, and the 273,927
records it classified positive rest on that unvalidated number. Meanwhile the training set being
assembled contains three properties (journal-class collinearity, abstract-presence perfectly
predicting positive, and source-label confounding) that would let a BERT score well for the wrong
reasons, and the retrieval query silently caps recall at ~78% before any model is involved. None of
these are hard to fix, and four of them are a day's work in total. The BM25/lexicon stage has reached
its natural limit — its remaining value is as an honestly-measured baseline, not as a system to
improve further. The highest-leverage next moves are: seal a test set, measure label agreement, fix
the three dataset confounds, then run an encoder bake-off with the same rigour Step 11 already applied
to scorers — with the tagging head aligned to DOME's own v2.0.0 schema fields, which turns "rich
tagging" from a feature into automated registry pre-population.

---

*Written 2026-08-02. All measurements taken against the repo at that date; live EPMC counts fetched
the same day. No code, config, or data was modified in producing this document.*
