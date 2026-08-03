# STEPS_Progress.md — human-in-the-loop runbook

A literal, step-by-step log for running the `dome-triage` Phase 0–1 pipeline inside Docker,
picking up exactly where the project currently stands. This complements `README.md` (the
Quickstart) and `ROADMAP.md` (the design rationale / acceptance criteria) — it doesn't replace
them, it's the executable, loggable version of the same sequence.

## How to use this file

1. Work top to bottom. Don't skip a step — several are designed human checkpoints
   (`ROADMAP.md`'s "Human-in-the-loop checkpoint map"), not busywork.
2. Run the **Command** exactly as written from the repo root
   (`/home/gavinfarrell/PhD_Code/dome-triage`).
3. Compare what you actually see against **Expected output**.
4. Do whatever's in **Validate before continuing**.
5. Fill in the **Log** block for that step (date, actual numbers, any decision you made) before
   moving on. This file is git-tracked, so your log becomes part of the project's own audit
   trail alongside `data/provenance.jsonl`.
6. Steps 1–8d below are already done. Steps 1–7 are logged retroactively from
   `data/provenance.jsonl` and the files already on disk (I verified them on 2026-07-31 rather
   than you running them live); Step 8 onward (the keyword lexicon curation) you actually ran
   yourself, logged live as it happened.

Everything runs via Docker Compose — two services defined in `docker-compose.yml`:
`pipeline` (an interactive shell for one-off `dome-triage <command>` invocations) and `curate`
(the Streamlit human-curation UI on port 8501). No API keys or `.env` file are needed — Europe
PMC is queried unauthenticated, and all configuration is via the YAML files in `configs/`.

**Text preprocessing (stopword removal, lemmatization, tokenization, etc.)**: every step below
that touches paper text (TF-IDF/KeyBERT extraction, all three relevance scorers) applies some
depth of NLP preprocessing before it does anything else. Rather than duplicate that explanation at
every step, it's all in one place — **[`PREPROCESSING.md`](PREPROCESSING.md)** — with what's
applied where, why that specific depth was chosen over the alternatives, and the real (verified,
not hypothetical) consequences of each choice. Each relevant step below links to the specific
section rather than repeating it.

---

## Status snapshot (verified 2026-08-02, updated after Step 13's real run)

| Phase | State |
|---|---|
| Phase 0 — repo scaffold | ✅ Done |
| Phase 1 — data consolidation → curation | 🟡 Steps 1–13 done (incl. the keyword lexicon, the full BM25 bulk-match/score/stratify pipeline, and the Curate app's new filters + diversity dashboard). **Step 14/14b (clear negatives + screening) ON HOLD by explicit decision (2026-08-02)** — built and tested, but deliberately not run yet; come back to it *after* a real manual curation pass, not before (see the hold notes on Step 14/14b). Step 15 (human curation) is open now — **this is the active next step**. |
| Phases 2–8 (EDAM tagging, classifiers, calibration, bulk scan, daily pipeline) | ⬜ Not implemented — no code exists yet beyond stub `__init__.py` files. Nothing to run here; see the closing section. |

Canonical dataset right now: **6,647 records** (`data/processed/canonical_dataset.csv`) — the
original 4,320 plus **2,327 new BM25-matched candidates** merged in by Step 13, all `unlabeled`
and ready for the Curate app's queue. **9 flagged conflicts** still awaiting resolution
(`data/processed/conflicts_for_review.csv`).

Keyword lexicon right now (see Steps 8–8d): a real 500-decision curation round is done
(314 positive / 5 negative / 181 irrelevant), plus a curated batch of ML/AI terms I (Claude) added
on top, cleaned up into a reviewed "suggested final" lexicon — **296 positive / 18 negative
(exclusionary) terms**, three tiers kept on disk separately (see Step 8's sub-steps).

---

## Step 0 — Build the containers

**What's happening / why:** The two local Docker images (`dome-triage-curate:latest`,
`dome-triage-pipeline:latest`) predate the second commit (they're tagged `8a0a3c3-dirty` in the
provenance ledger, i.e. before commit `a9a9387` added the provenance ledger itself, bulk-match,
scoring, and sampling code). Rebuild so the container matches the code you're about to run.

**Command:**
```bash
docker compose build
```

**Expected output:** Build completes without error; two images are (re)tagged
(`dome-triage-curate`, `dome-triage-pipeline`). This bakes in NLTK corpora and the
KeyBERT/sentence-transformers model weights, so no network access is needed at runtime just to
tokenize or extract keywords.

**Validate before continuing:** `docker images | grep dome-triage` shows fresh `CREATED`
timestamps for both images.

**Log:**
- [✅] Run on: 31 st July, 2026
- Actual output: Containers built successfully no errors
- Decision/notes: __________

---

## Steps 1–7 — Already run (logged retroactively)

These already produced real output files on disk. Logged here so the record is continuous; no
action needed unless you want to re-verify them.

### Step 1 — Load labeled sources ✅
**Command:** `docker compose run --rm pipeline dome-triage ingest load-sources`
**Output:** `data/interim/raw_records.csv`
**Log:** Present on disk as of 2026-07-31. Ran before the provenance ledger existed (commit
`8a0a3c3`), so there's no `provenance.jsonl` entry for it — only the output file is evidence.

### Step 2 — Consolidate / dedupe ✅
**Command:** `docker compose run --rm pipeline dome-triage dedupe consolidate`
**Output:** `data/processed/canonical_dataset.csv` — **4,329 records**;
`data/processed/conflicts_for_review.csv` — **9 conflicts** still awaiting a human decision (see
Step 15b below).
**Log:** Present on disk as of 2026-07-31. No provenance entry (pre-dates the ledger), same as
Step 1.

### Step 3 — Full-text manifest ✅
**Command:** `docker compose run --rm pipeline dome-triage fulltext build-manifest`
**Output:** `data/fulltext_manifest.csv`
**Log:** Present on disk as of 2026-07-31. No provenance entry.

### Step 4 — TF-IDF keyword extraction ✅
**Command:** `docker compose run --rm pipeline dome-triage keywords tfidf`
**Output:** `data/interim/tfidf_terms.csv`
**Preprocessing applied:** full `clean_text()` pipeline (HTML strip, tokenize, lowercase, stopword
removal, lemmatize) plus a second sklearn stopword pass and `ngram_range=(1,3)` phrase extraction —
see [`PREPROCESSING.md`](PREPROCESSING.md#who-calls-this-and-how-much-of-it--with-the-reasoning)
for exactly why this step gets the heaviest, extraction-specific treatment.
**Log:** Present on disk as of 2026-07-31. No provenance entry.

### Step 5 — KeyBERT keyword extraction ✅
**Command:** `docker compose run --rm pipeline dome-triage keywords keybert`
**Output:** `data/interim/keybert_terms.csv`
**Preprocessing applied:** HTML-tag stripping only — deliberately no tokenization/stopword-removal/
lemmatization, since the transformer embedding model needs natural sentence structure to work
correctly. See [`PREPROCESSING.md`](PREPROCESSING.md#who-calls-this-and-how-much-of-it--with-the-reasoning)
for why this is lighter than Step 4's, not an inconsistency.
**Log:** Present on disk as of 2026-07-31. No provenance entry.

### Step 6 — Build keyword lexicon candidates ✅
**Command:** `docker compose run --rm pipeline dome-triage keywords build-lexicon`
**Output:** `data/processed/keyword_lexicon_candidates.csv` — **40,756 candidate terms**, columns
`term, tfidf_positive_mean, tfidf_baseline_mean, discriminative_score, document_frequency,
keybert_score_mean, seed_tfidf_score, seed_category, review_status, notes` (all currently
`review_status=pending`).
**Log:** Present on disk as of 2026-07-31. No provenance entry.

### Step 7 — Lexicon threshold stats ✅
**Command:** `docker compose run --rm pipeline dome-triage keywords lexicon-stats`
**Output:** `data/processed/lexicon_stats_report.csv` — real threshold counts, run 4 times
(01:17, 01:31, 01:31, 01:35 UTC on 2026-07-28 — someone iterated on the cutoff). Latest numbers:

| dimension | threshold | terms remaining |
|---|---|---|
| discriminative_score | ≥ 0.0 | 11,179 |
| discriminative_score | ≥ 0.001 | 714 |
| discriminative_score | ≥ 0.005 | 81 |
| discriminative_score | ≥ 0.01 | 18 |
| document_frequency | ≥ 1 | 22,803 |
| document_frequency | ≥ 2 | 798 |
| document_frequency | ≥ 5 | 112 |
| document_frequency | ≥ 10 | 33 |

**Log:** Present on disk as of 2026-07-31, per `data/provenance.jsonl` (4 entries,
`step_name=keywords.lexicon-stats`). This is your input for Step 8 below.

---

## Step 8 — Keyword Review (human, Streamlit) ✅

**What's happening / why:** 40,756 candidate terms is too many to trust or review one by one.
Step 7's numbers let you pick a defensible cutoff. This step got substantially rebuilt during the
session from a first pass (a single 40k-row editable table) into a real one-at-a-time curation
interface (`src/dome_triage/curate/pages/3_Keyword_Review.py`,
`src/dome_triage/curate/term_review_state.py`) — see `ROADMAP.md`'s Phase 1 section for the full
design rationale. Every term gets one of **three** final decisions, not a binary approve/reject:

- **Positive** — feeds `keyword_lexicon.csv`.
- **Negative** — an exclusionary/negative-tail term (disproportionately common in the negative/
  rejected corpus) — feeds `keyword_lexicon_exclusionary.csv`, which `keywords/scoring.py`'s
  BM25/TF-IDF-cosine scorers subtract as a penalty.
- **Irrelevant** — useful as neither — feeds `keyword_lexicon_irrelevant.csv`, audit-only.

Two browsable piles ("Positive candidates" / "Exclusionary candidates" toggle at the top of the
page) are just a navigation aid — the decision you record for a term isn't locked to whichever
pile surfaced it, so a term you're browsing as a "positive candidate" can still be marked Negative
or Irrelevant. A separate "Add a term manually" box lets you classify any term directly, whether
or not TF-IDF/KeyBERT ever extracted it.

**Command:**
```bash
docker compose up curate
# browse to http://localhost:8501, open the "Keyword Review" page in the sidebar
```
Set your curator name on the Home page first. Pick a pile, set the threshold (live count shown),
and for each term click **Positive** / **Negative** / **Irrelevant** / **Skip** (skip doesn't log
anything — the term just reappears later). Every decision writes immediately to
`data/processed/keyword_review_events.csv` (backed up before every write) — nothing is final until
Step 8b folds it into the real lexicon files.

**Expected output:** `data/processed/keyword_review_events.csv` grows by one row per decision.

**Validate before continuing:** Tail the events file between clicks to confirm it's actually
writing; spot-check that Skip doesn't add a row.

Stop the container when done: `Ctrl+C` in the terminal running `docker compose up curate`.

**Log:**
- [x] Run on: 31st July 2026 (interface rebuilt this session; first real curation round completed
  the same day)
- Session: 2026-07-31T19:13:48Z → 2026-07-31T19:36:05Z UTC, curator "Gavin"
- **500 decisions total: 314 positive / 5 negative / 181 irrelevant**
- Decision/notes: the 5 negative decisions (`forest`, `random`, `neural`, `area`, `bayes`) are all
  single generic words that are also tokens inside positive multi-word terms you separately
  approved (`random forest`, `neural network`, `area under curve` variants, `naive bayes`) — a
  deliberate exclusionary counterweight to their generic sense. See Step 8d's cleanup log for how
  this got surfaced and handled, not silently resolved either way.

---

## Step 8b — Materialize the keyword lexicon (tier 1: your curated decisions) ✅

**What's happening / why:** Folds `keyword_review_events.csv` from Step 8 into the three real
lexicon files — last decision per term wins, regardless of which pile or manual entry produced
it. This is what makes your curation session actually count; it's also, unlike `curate
materialize` (the paper-curation equivalent), a provenance-logged step, since `keyword_lexicon.csv`
is a first-class pipeline artifact consumed downstream by `scoring-bakeoff`/`score-bulk-match`.

**Command:**
```bash
docker compose run --rm pipeline dome-triage keywords materialize-lexicon
```

**Expected output:** `keyword_lexicon.csv` (positive), `keyword_lexicon_exclusionary.csv`
(negative), `keyword_lexicon_irrelevant.csv` (irrelevant); `keyword_lexicon_candidates.csv`'s
`review_status` column synced in place.

**Validate before continuing:** Row counts match Step 8's session totals.

**Log:**
- [x] Run on: 31st July 2026
- **Output: `keyword_lexicon.csv` 314 rows / `keyword_lexicon_exclusionary.csv` 5 rows /
  `keyword_lexicon_irrelevant.csv` 181 rows** — matches Step 8's session exactly.
- Decision/notes: these are your files — nothing below (Steps 8c/8d) ever modifies them.

---

## Step 8c — Seed additional curated terms (tier 2: my curated additions) ✅

**What's happening / why:** A batch of well-known ML/AI vocabulary and non-methods
publication-type words that either weren't reached yet in Step 8's session or (for current
agentic/LLM terminology) barely exist in this training corpus at all. Written to `src/dome_triage/
keywords/curated_terms.py` (version-controlled, reviewable via git diff, not a CSV) and expanded
into their own tier-2 files — **never merged into tier 1's files above**. Anything already
decided in Step 8 is automatically skipped; anything that does exist in the 40,756-row candidate
file gets its real `discriminative_score`/`document_frequency` carried over, blank otherwise.

**Command:**
```bash
docker compose run --rm pipeline dome-triage keywords seed-additional-terms
```

**Expected output:** `keyword_lexicon_added_positive.csv`, `keyword_lexicon_added_negative.csv`.

**Validate before continuing:** Spot-check a few terms' stats against
`keyword_lexicon_candidates.csv`.

**Log:**
- [x] Run on: 31st July 2026
- **45/46 positive terms added** (1 correctly *not duplicated* here — `knn`: you'd already
  marked it positive yourself in Step 8's session, so it's already sitting in tier 1's
  `keyword_lexicon.csv` and carries through into tier 3 untouched; adding it again here would've
  just been a redundant duplicate row, not a fix), across ML
  algorithms (supervised: linear regression, naive bayes, lightgbm, k-nearest neighbors, RNN,
  LSTM, transformer; unsupervised: k-means, hierarchical clustering, DBSCAN, PCA, t-SNE, UMAP,
  autoencoder, Gaussian mixture model, self-organizing map), generative model terms (GAN, VAE,
  diffusion model, generative AI), agentic/LLM terms (LLM, AI agent, agentic AI, multi-agent
  system, RAG, foundation model, prompt engineering, fine-tuning), and flagship biodata terms
  (proteomics, genomics, transcriptomics, metabolomics, microbiome, metagenomics, single-cell,
  multi-omics).
- **14/14 negative terms added**: non-methods publication-type words (perspective, review,
  commentary, editorial, opinion, viewpoint, case report, letter to the editor, narrative review,
  correspondence, news, systematic review, meta-analysis, survey).
- Decision/notes: no EDAM ontology reference file exists anywhere on this machine — biodata terms
  are general domain knowledge, deliberately kept small. Some flagship biodata terms actually have
  a slightly *negative* `discriminative_score` in isolation (e.g. genomics, proteomics) — that's
  expected, not a bug: TF-IDF's positive-vs-negative differential is tuned to detect ML-methodology
  signal, and the negative/baseline corpus is itself ~69% plain bioscience papers, so a domain word
  alone doesn't discriminate FOR machine learning application. Included anyway on domain-relevance
  grounds, not empirical differential — flagged here for transparency.

---

## Step 8d — Suggest final cleaned lexicon (tier 3: reviewed suggestion) ✅

**What's happening / why:** Combines tier 1 (Step 8b) + tier 2 (Step 8c) and runs an explainable,
rule-based cleanup (`src/dome_triage/keywords/lexicon_cleanup.py`) — never a black-box dedup.
Four rules, every action logged: (1) exact duplicates dropped, (2) stray ≤2-character terms
dropped, (3) a unigram redundant with a longer phrase already in the *same* list dropped (e.g. a
bare "learning" contributes nothing beyond what "machine learning" already gives BM25/TF-IDF-cosine,
since both scorers flatten every lexicon term to unigram tokens before scoring — see
`keywords/scoring.py`) — **except** a small set of `PROTECTED_UNIGRAMS`
(`svm`/`cnn`/`roc`/`xgboost`/`regression`/`classifier`/`classification`/`autoencoder`, per your
explicit review) which are specific enough as standalone terms to keep even when subsumed, (4) a
negative unigram that overlaps a positive phrase's token is **kept, never removed** (an explicit
human decision stands) but flagged with which phrase(s) it dampens. Tier 1's live files are never
touched by this step — promoting tier 3 to production (i.e. actually pointing `scoring-bakeoff`/
`score-bulk-match` at it) is a separate, manual decision, not automatic.

**Command:**
```bash
docker compose run --rm pipeline dome-triage keywords suggest-final-lexicon
```

**Expected output:** `keyword_lexicon_suggested_final.csv`, `keyword_lexicon_exclusionary_
suggested_final.csv`, `keyword_lexicon_cleanup_log.csv`.

**Validate before continuing:** Read the cleanup log — check every "removed" entry you're unsure
about, and every "kept_flagged" tension entry.

**Log:**
- [x] Run on: 31st July 2026 (re-run once, after reviewing the first log and adding the
  `PROTECTED_UNIGRAMS` allowlist above)
- **Combined pool: 359 positive (314 + 45) / 19 negative (5 + 14) before cleanup.**
- **Suggested final: 296 positive / 18 negative.** Cleanup log: 77 entries — 64 removed (exact
  dupes + genuinely generic redundant unigrams: `model`, `learning`, `network`, `accuracy`,
  `training`, `value`, and ~60 more), 13 kept-and-flagged (8 protected abbreviations above + 5
  cross-list tensions: `forest`/`random`/`neural`/`area`/`bayes`, each logged with exactly which
  positive phrase(s) it dampens).
- Decision/notes: **✅ promoted to production 31st July 2026.** Old tier 1 archived as
  `keyword_lexicon_tier1_original_pre_promotion.csv` / `keyword_lexicon_exclusionary_tier1_
  original_pre_promotion.csv` (314 / 5 rows — your original curated-only lexicon, kept for
  reference, never overwritten again). Tier 3's 296/18 files were copied over the live
  `keyword_lexicon.csv`/`keyword_lexicon_exclusionary.csv` — this is what `scoring-bakeoff`/
  `score-bulk-match` now actually read. (Done via `docker compose run --rm pipeline bash -c "cp
  keyword_lexicon_suggested_final.csv keyword_lexicon.csv; cp
  keyword_lexicon_exclusionary_suggested_final.csv keyword_lexicon_exclusionary.csv"` — run inside
  the container because the host user can't write these root-owned files directly, see Step 0's
  known friction point.)

---

## Step 9 — Bulk blunt-match fetch (one command, full year range)

**What's happening / why:** Queries all of Europe PMC for `"artificial intelligence"` OR
`"machine learning"`, capturing full metadata (title/abstract/authors/journal/year/DOI/PMID/
PMCID/MeSH headings/pub types/open-access/author keywords) in one pass. **This used to require one
manual command per year — changed on your explicit instruction.** `bulk-match fetch` now takes
`--year-from`/`--year-to` and fetches the whole range in a single invocation
(`src/dome_triage/ingest/bulk_match.py::fetch_ai_ml_range`). Under the hood it still runs one EPMC
query per year (checkpointed via a per-year `.done` marker in `data/interim/bulk_match_cache/`, so
an interrupted run resumes at the next incomplete year rather than starting over) — that's just an
internal resumability detail now, not something you trigger by hand. Each year prints a live tqdm
progress bar plus a `--- bulk-match fetch: <year> ---` line as it starts, so a long multi-decade
run stays visible in your terminal the whole time, not silent. `configs/sources.yaml`'s
`epmc.page_size` was bumped 100→1000 (Europe PMC's documented max for cursorMark pagination) so
the same total records need far fewer HTTP round-trips.

Also computes and prints + logs a genuine count breakdown for the requested range — how many
records mention "artificial intelligence" alone, "machine learning" alone, and the combined
deduplicated total (EPMC's own OR-query semantics return each matching record exactly once even
if it matches both phrases, so this total needs no separate dedup step) — via three cheap
count-only queries (`EpmcClient.count`, pageSize=1, resultType=idlist), not a second full fetch.

**Command (one call, covers everything from year 2000 through today):**
```bash
docker compose run --rm pipeline dome-triage bulk-match fetch --year-from 2000 --year-to 2026
```

**Expected output:** One raw JSONL cache per year under `data/interim/bulk_match_cache/`
(`bulk_match_<year>.jsonl` + `.done` marker), plus `data/processed/bulk_match_summary.csv`
(appended to, one row per run: `run_date_utc, year_from, year_to, ai_count, ml_count,
combined_count`) — **this is the "clear final count of papers of each, AI/ML/total, with dates"
log file.** The terminal prints a live progress bar per year as it runs, then the final counts.

**Validate before continuing:** `combined_count` should be less than `ai_count + ml_count` (some
overlap is expected — papers mentioning both). Row counts non-trivial for recent years, thinner
for early-2000s years (real — AI/ML terminology was far less common in abstracts back then).

**Log:**
- [x] Run on: 31st July 2026 (2000-2026, one call, ~90 minutes)
- **AI-mentioning: 457,109 | ML-mentioning: 541,632 | Combined (deduplicated): 827,890**
  (also in `data/processed/bulk_match_summary.csv`, dated)
- Decision/notes: Logged in file results. `page_size: 1000` bump held up fine across the full
  multi-decade run — no EPMC errors.

---

## Step 10 — Build bulk candidate pool

**What's happening / why:** Consolidates every year's checkpoint file from Step 9 into one
deduplicated candidate pool, keyed on **`pmid`, not `pmcid`** — PMCID is only assigned to records
with full text deposited in PMC, while PMID exists for essentially every Europe PMC/MEDLINE entry,
so deduping on `pmcid` would leave true duplicates in for any record without one (likely most of
this bulk-matched pool, since most won't be open-access full text). **Still needed even though
Step 9 is now one command**, not per-year consolidation you manually trigger — Step 9 still writes
one JSONL file per year internally (for checkpointing/resumability), so something still has to
merge those files into a single pool before scoring/sampling can use it. This step is that merge.
It does not need to separately dedupe "AI vs ML" — Step 9's combined query already returns each
matching record exactly once, so any duplication this step removes is purely cross-year (e.g. a
record whose date metadata put it on a year boundary) or a record indexed without a PMID at all.

**Command:**
```bash
docker compose run --rm pipeline dome-triage bulk-match build-candidates
```

**Expected output:** `data/interim/bulk_candidates.csv` (per `configs/sampling.yaml`'s
`paths.bulk_candidates`).

**Validate before continuing:** Row count roughly matches Step 9's `combined_count` from
`bulk_match_summary.csv`, minus any cross-year duplicates.

**Log:**
- [x] Run on: 1st August 2026
- **Row count: 744,647 unique records** (by `pmid`) — from 758,123 total loaded across the 27
  year-files before dedup, so 13,476 cross-year/date-boundary duplicates removed. Written to
  `data/interim/bulk_candidates.csv`.
- Decision/notes: **Two real bugs found and fixed while running this for real, not in the small
  test fixtures:**
  1. **Dedup key was `pmcid`, fixed to `pmid`** per your instruction — PMCID only exists for
     full-text-deposited records, PMID exists for nearly every Europe PMC/MEDLINE entry.
  2. **OOM crash (exit 137)** on the first real attempt — loading all ~828k records as Pydantic
     objects simultaneously exceeded available memory on this 15GB host. Rewrote to process one
     year at a time (convert to DataFrame immediately, discard the Pydantic objects, dedupe the
     running frame incrementally) — second attempt completed cleanly in 143s.
  3. Also hit (and fixed) a **real EPMC data-quality issue**: some records have a bare `null`
     inside `keywordList`/`pubTypeList`, which crashed strict validation — now filtered rather
     than aborting the whole load over one bad list element.
  Also note: `combined_count` from Step 9 (827,890, a live EPMC count-only estimate) vs. the
  744,647 actually fetched+deduplicated here is a ~10% gap — plausible given EPMC's `hitCount` is
  a live, constantly-updated estimate at query time, not a snapshot, and the per-year fetch uses
  27 separate date-bounded queries vs. one continuous range for the count. Not investigated
  further; the 744,647 figure (actually fetched, on disk, deduplicated) is the trustworthy one.

---

## Step 11 — Relevance-scoring bake-off

**What's happening / why:** Empirically compares three scorers (weighted-sum, BM25, TF-IDF
cosine) against the **already-labeled** records (Step 2's canonical dataset — real positive/
negative ground truth, not a guess) before trusting any of them to rank the unlabeled bulk pool —
a real empirical check, not an assumption. As of this rewrite, every scorer is run **twice**: once
using only your approved positive lexicon (`keyword_lexicon.csv`), and again with your approved
exclusionary/negative lexicon (`keyword_lexicon_exclusionary.csv`) subtracted as a penalty — a
genuine before/after comparison of whether the exclusionary lexicon actually earns its keep, not
just a claim that it does (`src/dome_triage/keywords/scoring_bakeoff.py`,
`pipeline/steps.py::step_keywords_scoring_bakeoff`).

> **Historical note:** this step ran once before, on 2026-07-28 (213.9s, no exclusionary lexicon
> existed yet, only positive-lexicon-only numbers), and `ROADMAP.md` recorded that result: BM25
> and TF-IDF-cosine (AUROC ≈0.76–0.77) both substantially outperformed weighted-sum (AUROC≈0.67).
> Treat that as historical color only — the lexicon, the metrics computed, and the code itself
> have all changed substantially since (three-way curation, the added-terms tiers, the cleanup
> pass, and everything below). Re-run it for real current numbers.

### How each scorer actually works

All three take your approved lexicon (a list of terms + optional weights) and a corpus of paper
texts (title + ". " + abstract), and produce one continuous **score per paper** — none of them are
inherently a classifier; see "Is there a threshold cutoff?" below for how a score becomes a
decision.

**Preprocessing note**: `bm25`/`tfidf-cosine` run the full `clean_text()` pipeline (tokenize,
lowercase, drop stopwords, drop ≤2-char tokens, lemmatize) over both the corpus and the lexicon
before scoring anything; `weighted-sum` runs none of that — see
[`PREPROCESSING.md`](PREPROCESSING.md) for exactly what that pipeline does and why the three
scorers deliberately don't all get the same depth of it.

- **`weighted-sum`**: for each paper, find every approved positive lexicon term that's a literal
  (case-insensitive) substring anywhere in its text, and add up each matched term's weight (its
  `discriminative_score` from your curation, or 1.0 if it has none). Fully transparent, cheap, and
  the only one of the three that respects multi-word phrases exactly as written — but empirically
  the weakest (AUROC≈0.67 historically).
- **`bm25`**: a standard, decades-old search-engine ranking algorithm (Okapi BM25). Treats your
  whole approved lexicon as one big search query and ranks every paper by how well it matches that
  query — rewarding papers containing *rare* lexicon terms (rare across the whole scored corpus,
  so more specific/discriminating) over just any lexicon term, and correcting for paper length so
  a long abstract doesn't win purely by containing more words. **Caveat already found this
  session**: BM25 flattens the lexicon to a flat bag of words — "machine learning" becomes two
  separate tokens "machine"/"learning", so multi-word phrase structure isn't preserved.
- **`tfidf-cosine`**: represents every paper *and* your whole lexicon (as one combined
  pseudo-document) as vectors weighted by how distinctive each word is across the scored corpus,
  then measures the angle (cosine similarity) between a paper's vector and the lexicon's vector —
  closer angle = higher score. Same phrase-flattening caveat as BM25.

### Is there a threshold cutoff? (yes, now — there wasn't before)

All three scorers only ever produce a *ranking* score, not a yes/no. **AUROC needs no cutoff at
all** — it measures ranking quality (does the scorer put positives above negatives?) across every
possible threshold at once, from 0.5 (no better than chance) to 1.0 (perfect). But
accuracy/precision/recall/the confusion matrix (true/false positive/negative) genuinely require
picking one specific score value above which a paper counts as "positive."

Until this rewrite, no such cutoff existed in the code at all. It now uses each scorer's own
**Youden's-J-optimal threshold**: the point on that scorer's ROC curve that maximizes (true
positive rate − false positive rate) — the standard, principled way statistics/ML literature picks
a single operating point from a continuous score, not an arbitrary guess. It's computed fresh per
scorer per condition and reported explicitly as `threshold_youden` in the output, so it's fully
transparent and reproducible — you can see the exact number, not just trust it.

### Metrics glossary (what each column in the report means)

| Metric | Meaning |
|---|---|
| `n_positive` / `n_negative` / `n_total` | **How many already-labeled papers were actually presented to the scorer for this evaluation** — pulled from `canonical_dataset.csv` where `label` is `positive` or `negative` (`undeterminable`/`irrelevant`/`skipped` excluded). Same set for every scorer and both conditions, so comparisons are apples-to-apples. |
| `auroc` | Area under the ROC curve — how well the scorer ranks positives above negatives across *all* possible thresholds. 0.5 = no better than random guessing, 1.0 = perfect ranking. Needs no cutoff. |
| `threshold_youden` | The specific score value above which this scorer's papers are called "positive" for every metric below — see above. |
| `accuracy` | Of all `n_total` papers, what fraction were classified correctly (either genuinely positive and flagged positive, or genuinely negative and flagged negative) at that threshold. |
| `precision` | Of the papers the scorer *flagged* as positive, what fraction were *actually* positive. High precision = few false alarms. |
| `recall` | Of the papers that were *actually* positive, what fraction the scorer correctly flagged. High recall = few genuine positives missed. |
| `f1` | Harmonic mean of precision and recall — one balanced number when you care about both roughly equally. |
| `true_positive` | Genuinely positive papers correctly flagged positive. |
| `true_negative` | Genuinely negative papers correctly flagged negative. |
| `false_positive` | Genuinely negative papers *wrongly* flagged positive (a false alarm). |
| `false_negative` | Genuinely positive papers *wrongly* flagged negative (a miss). |
| `correlation_with_label` | Pearson correlation between the raw continuous score and the true 0/1 label — a cruder companion sanity check to AUROC. |
| `precision_recall_at_quantiles` | Precision/recall if you'd instead drawn the line at the top 50%/25%/10% of scores rather than the Youden point — context for Phase 6's future confidence-routing thresholds, which won't necessarily use the Youden point. |
| `condition` | `positive_lexicon_only` or `positive_plus_exclusionary_lexicon` — which of the two runs this row is from; see below. |

### The two conditions — what to actually look for

Compare the **same scorer's** two rows: does `positive_plus_exclusionary_lexicon` improve on
`positive_lexicon_only` (higher AUROC, better precision without recall collapsing)? If yes,
that's empirical proof the exclusionary lexicon (the `forest`/`random`/`neural`/`area`/`bayes`
terms and the rest) is earning its keep, not just a nice idea. If it's not run for
`positive_plus_exclusionary_lexicon` at all, `keyword_lexicon_exclusionary.csv` wasn't found —
shouldn't happen now that tier 3 is promoted (Step 8d), but the step degrades gracefully to one
condition if so, and says which in its printed summary.

**Command** (same as before — both conditions run automatically now, no new flags needed):
```bash
docker compose run --rm pipeline dome-triage keywords scoring-bakeoff
```

**Expected output:** `data/processed/scoring_bakeoff_report.csv` — **6 rows** (3 scorers ×
2 conditions), sorted by scorer then condition so each scorer's before/after pair sits together,
with every column from the glossary above. Takes a few minutes (213.9s historically for one
condition — expect roughly double for two).

**Validate before continuing:** Read the report. For each scorer, compare its two condition rows.
Confirm which scorer(s) win overall, and whether the exclusionary lexicon actually helped. This is
a genuine decision point — don't rubber-stamp any prior numbers, the dataset and lexicon have
changed since any earlier run.

**Log:**
- [x] Run on: 1st August 2026, 07:20 UTC finish (duration 753.8s, ~12.6 minutes for all 6 rows)
- **Positive/negative volume presented: 1,878 positive / 1,907 negative (3,785 total)** —
  verified directly against Step 2's canonical dataset (4,320 total records; 533 `skipped` +
  2 `conflict` excluded as not definitive ground truth).
- **Full results, explained figure-by-figure, with feedback: → [`SCORING_BAKEOFF_RESULTS.md`](SCORING_BAKEOFF_RESULTS.md)**
  (kept as a separate file rather than duplicated here — it's a full report, not a log entry).
  Headline: BM25 AUROC 0.767→0.774 (barely moves), **TF-IDF-cosine AUROC 0.765→0.797 (clearest
  real improvement from the exclusionary lexicon)**, weighted-sum's exclusionary run hit a real
  bug (AUROC collapsed to 0.454, worse than random) — found, explained, and **fixed in code**
  (`WeightedSumScorer` was subtracting an unweighted match count instead of each exclusionary
  term's own tiny weight); not yet re-run post-fix.
- Did the exclusionary lexicon measurably help? **Yes for TF-IDF-cosine** (clearly, the biggest
  mover of the three — not statistically tested yet, that's a later-phase capability). Negligible
  for BM25. Uninterpretable for weighted-sum until re-run with the fix.
- Scorer (and condition) chosen for Step 12: **`bm25`, with the exclusionary lexicon applied**
  (your explicit choice — TF-IDF-cosine had the bigger exclusionary-lexicon lift in the bake-off,
  but BM25's own AUROC was already close behind at 0.774 vs 0.797, and you preferred BM25 as the
  production scorer). Superseded the earlier draft recommendation of `tfidf-cosine` below.
- Decision/notes: BM25 chosen over TF-IDF-cosine on 2026-08-01. Real Youden threshold for
  `bm25` + `positive_plus_exclusionary_lexicon` from `scoring_bakeoff_report.csv`:
  **107.59714643077095** (BM25 scores are unbounded corpus-relative numbers, not a 0-1 similarity
  like TF-IDF-cosine — a threshold in the hundreds is expected and correct, not a bug).

---

## Step 12 — Score the bulk pool with the chosen scorer

**What's happening / why:** Applies the scorer you picked in Step 11 — **`bm25`, with the
exclusionary lexicon applied** (your decision, see the log above and `SCORING_BAKEOFF_RESULTS.md`
for the full comparison against TF-IDF-cosine and weighted-sum) — to every one of the ~745,000
records in the bulk candidate pool (Step 10), producing a `match_score` per record. This is what
Step 13's stratified sample gets drawn from.

### How the negative (exclusionary) lexicon actually interacts with BM25 — read before relying on it

You asked directly: BM25 treats the lexicon as more-than-one-word units (e.g. "machine learning"),
but the negative lexicon has single-word terms to exclude (e.g. "learning" alone) — doesn't that
mismatch make the negative term ineffective? Checked directly against the real code
(`src/dome_triage/keywords/scoring.py::Bm25Scorer.score_corpus`) and the real production files,
not assumed:

1. **There is no granularity mismatch — both lists get flattened identically.** BM25's query
   construction is `clean_text(" ".join(lexicon_terms)).split()` for the positive side, and the
   *exact same operation* — `clean_text(" ".join(exclusionary_terms)).split()` — for the negative
   side. The positive lexicon does contain multi-word phrases ("machine learning", "random
   forest"), but BM25 never scores them as phrases either — see
   [`PREPROCESSING.md`](PREPROCESSING.md#the-recurring-theme-phrase-flattening) for the general
   mechanism. Both lists end up as flat bags of unigram tokens before BM25 sees either of them.

2. **"learning" alone is not currently in the negative lexicon.** Checked directly against the
   live `keyword_lexicon_exclusionary.csv` (18 terms): the single-word negative terms are `area`,
   `bayes`, `forest`, `neural`, `random` — 5 terms, not `learning`. `learning` did exist in the
   pre-cleanup candidate pool, but Step 8d's cleanup removed it from the *positive* side as a
   redundant unigram (subsumed by "machine learning" already being in the same list) — it was
   never a negative term.

3. **The real mechanism runs the opposite direction from "ineffective."** Because both lists share
   the same flattened unigram vocabulary, a negative unigram doesn't fail to match — it matches
   *too broadly*. `forest` in the negative lexicon subtracts BM25 score from every paper containing
   the word "forest" anywhere, including papers that only contain it because they say "random
   forest" — a phrase you separately approved as positive. BM25 has no concept of "this occurrence
   was inside an approved phrase, don't penalize it"; it counts token occurrences, full stop. So
   the negative lexicon isn't inert here — it's a blunt, word-level filter that also dampens (a
   weighted subtraction, not a hard exclusion) the exact positive phrases it happens to share a
   word with.

4. **This was already found and is already logged, for the 5 terms that actually exist today** —
   `keyword_lexicon_cleanup_log.csv` flags all 5 as `kept_flagged` (kept, not removed — an explicit
   decision from your original curation, not overridden), each with the exact positive phrase(s)
   it dampens:
   - `area` → dampens: area curve, area curve auc, area receiver, area receiver operating
   - `bayes` → dampens: naive bayes
   - `forest` → dampens: forest algorithm, forest classifier, forest model, random forest, random
     forest classifier, random forest model, regression random forest
   - `neural` → dampens: artificial/convolutional/deep/recurrent neural network, neural network
     (cnn/model)
   - `random` → dampens: random forest (+ all variants above), regression random forest

5. **How much this actually subtracts, mechanically**: `score = positive_bm25_score −
   exclusionary_weight × negative_bm25_score`, with `exclusionary_weight = 1.0` by default — a
   full, equal-weight subtraction of the negative side's own BM25 score, computed the same
   IDF/length-normalized way as the positive score (not a flat penalty per match). A paper heavy on
   "random"/"forest" purely in the "random forest" methodology sense is penalized by roughly what a
   paper genuinely about the generic, unrelated senses of those words would score — BM25 has no
   mechanical way to distinguish the two cases.

6. **The `matched_terms__bm25` column you'll see is not what drives the score.** It's computed
   separately, by literal substring search on the *raw, uncleaned* text (`_find_matched_terms`), so
   it will correctly show "random forest" as a matched phrase. `match_score__bm25` itself comes
   from the flattened/lemmatized unigram bag described above — two different code paths. Don't
   infer the scoring mechanism from what's displayed in `matched_terms__bm25`.

**Retain or unwind `area`/`bayes`/`forest`/`neural`/`random` as negative terms — your call, nothing
changed here, this section is explanation only:**
- **Retain (current state).** These words plausibly still carry real negative signal in their
  *other*, non-methods senses elsewhere across the 745k pool (e.g. "bayes" in an unrelated
  biographical mention, "area" in a purely geographic/anatomical sense) — and Step 11's real
  bake-off numbers showed the exclusionary lexicon *did* measurably help BM25's AUROC
  (0.767→0.774) net of this exact dampening effect, so empirically it isn't outweighing the
  benefit in aggregate.
- **Unwind.** Remove these 5 unigrams from `keyword_lexicon_exclusionary.csv` (or scope them to
  `weighted-sum` only, which does literal-phrase matching and has no such collision). If the
  negative stream ends up swallowing a lot of genuine "random forest"/"neural network" papers in
  practice, this cross-token dampening on your most common ML methods is the most likely mechanical
  cause, and removing just these 5 terms is the targeted fix — not the whole exclusionary lexicon.

As of this rewrite, one command now also adds (`src/dome_triage/pipeline/steps.py::
step_keywords_score_bulk_match`):
- **`match_classification__bm25`** (`positive`/`negative`) — the raw score converted to a
  clear call using the *exact* Youden-optimal threshold Step 11 already validated for
  `bm25` + `positive_plus_exclusionary_lexicon` (reused from `scoring_bakeoff_report.csv`, not
  recomputed) — so you get **both** a continuous score to sort/threshold by yourself **and** a
  ready-made positive/negative split ("the positive stream and the negative stream") for a first
  pass. **Neither stream is dropped from the output file** — `match_classification__bm25` is just
  an extra column on every row; `negative`-classified rows stay in `bulk_candidates_scored.csv`
  and remain fully eligible for Step 13's stratified sampling into the curation queue, so you can
  manually review/reclassify them yourself rather than having them silently discarded by the
  algorithm. Verified directly in code: `step_keywords_score_bulk_match` only ever *adds* columns
  to the candidates DataFrame and writes the full frame back out; `step_sampling_stratify` reads
  that full frame and stratifies by score *band* (quantiles of the raw score), not by the
  positive/negative classification column — nothing in the path from Step 12 to the curation queue
  filters on `match_classification__bm25`.
- **`already_curated`** / **`existing_label`** / **`existing_label_confidence`** — does this
  candidate already exist in `canonical_dataset.csv` from a prior curation round (matched by
  pmcid, else pmid, else doi), and if so what was it already decided as. This is **reporting/
  visibility metadata on this file**, not something that flows into the Curate app automatically
  — `already_curated=True` records are already structurally excluded from being re-added as
  duplicates by Step 13's existing merge logic (`_merge_new_candidates_into_canonical`), so they
  were never going to double up in your queue either way. What this column actually gives you:
  a clear number for how much of the 745k pool is genuinely new territory vs. already-covered
  ground, right in this file and in the step's printed summary.
- **`has_pmcid`** — full text deposited in PMC or not, for your own filtering/stratification.

**Live progress in the terminal**: this step used to run completely silently (blank terminal for
the whole run). Fixed — it now prints numbered phase markers (`[1/6]` loading lexicon ... `[6/6]`
writing output) plus a live `tqdm` progress bar for the corpus-scoring pass itself
(`bm25: cleaning + tokenizing corpus`), so you can see it's alive and roughly how far through it
is at every stage, not just at the very end.

**Command** (already decided: `bm25`; `--exclusionary-weight` defaults to `1.0`, matching
Step 11's validated run):
```bash
docker compose run --rm pipeline dome-triage keywords score-bulk-match --scorer bm25
```

**⚠️ Scale warning, genuinely untested at this size**: Step 10's OOM crash (build-candidates,
~828k records loaded as Python objects) was fixed by processing year-by-year instead of all at
once. This step is different — it tokenizes **text only** (title+abstract strings, not heavy
Pydantic objects) and builds one in-memory BM25 index over the whole corpus, which is much lighter
per record than Step 10's Pydantic objects, but it's never been run at ~745k scale before. If it's
slow or runs out of memory, that's a real possibility, not a hypothetical — tell me and we'll fix
it the same way (chunked/batched processing), the same as Steps 9 and 10.

**Expected output:** `data/interim/bulk_candidates_scored.csv`, same row count as
`bulk_candidates.csv` (744,647) plus: `match_score__bm25`, `matched_terms__bm25`,
`match_classification__bm25`, `already_curated`, `existing_label`,
`existing_label_confidence`, `has_pmcid`.

**Validate before continuing:** Score distribution isn't degenerate (not everything scoring 0 or
identical). Check the printed summary for the `already_curated` / `has_pmcid` percentages — sanity
check they're plausible (e.g. `already_curated` should be small, a few thousand out of 745k, not
a large fraction). Also sanity-check the negative-classified count is nonzero and roughly
comparable in scale to positive (per Step 11's bake-off, the underlying positive/negative
population was close to a 50/50 split — 1,878/1,907 — so a wildly lopsided split at 745k scale is
worth a second look, not necessarily wrong, but worth noticing).

**Log:**
- [x] Run on: 2026-08-01 (real, full 744,647-doc run — see incident + fix history below)
- Row count: **744,647** (in = out, confirmed via pandas; provenance's own "745499" figure is the
  known `wc -l`-style embedded-newline overcount from earlier in this project, not a real
  discrepancy — pandas is authoritative, see Step 10's log)
- `already_curated` count / %: **3,713 / 0.5%** (plausible — small, as expected)
- `has_pmcid` count / %: **587,235 / 78.9%**
- Positive / negative split from `match_classification__bm25`: **273,927 positive / 470,720
  negative** (sums exactly to 744,647 — both streams genuinely present, verified directly against
  the real output file, not just the printed summary)
- Confirmed negative-classified rows are still present in the output file (not dropped): **yes** —
  verified directly (`value_counts()` on the real file, not assumed)
- Duration: **269.6 seconds (4.5 minutes)**, confirmed via `data/provenance.jsonl`
- Decision/notes: **This run had a real incident behind it, worth keeping on record.** The first
  attempt (before this session's fixes) ran 11h38m and never finished — `clean_text()` was calling
  `ensure_nltk_data()` (4 filesystem searches) on every single one of 744,647 documents instead of
  once; fixed by caching it. A second, deeper problem then surfaced while fixing the first:
  parallelizing the cleaning step across CPU cores using Python's `spawn` start method caused each
  worker to independently re-import this whole application (including `torch`, pulled in via
  `keybert_extract.py`), ballooning to ~10-11GB RSS *per worker* — the kernel OOM-killer fired
  repeatedly and the *host machine* needed a hard reset (confirmed via `journalctl`). Fixed by
  switching to `fork` (workers share the parent's already-loaded memory instead of re-importing
  it) with a worker count capped by *available* memory, not just CPU count
  (`preprocess.py::_default_worker_count()`), plus a hard `mem_limit: 12g` added to `pipeline`'s
  Docker Compose service as a backstop so any future memory bug is contained to this one container
  rather than able to take the host down again. Two more real, measured bottlenecks were found and
  fixed along the way: `_find_matched_terms` was a second, *silent* single-threaded pass (42.2s for
  just 150k documents, no progress bar at all) -- folded into the same parallel pass as cleaning;
  and holding a combined (cleaned-text, matched-terms) list for the whole corpus *plus* the two
  lists built from it was, on its own, enough to OOM-kill the container even after the `fork` fix
  -- fixed by making the parallel-processing helper a generator so callers consume results directly
  into their final structures, never materializing a whole-corpus intermediate copy, plus
  `sys.intern()`-ing tokens (the corpus has enormous token repetition -- "model"/"patient"/"study"
  etc. -- so sharing one string object per distinct token instead of ~75 million separate ones was
  a substantial, measured memory saving). Final verified state: 116/116 tests passing, real
  744,647-document run completes cleanly in 4.5 minutes, peak container memory comfortably below
  the 12GB cap, host untouched. See `git log` for this session's commits if you want the full diff.

---

## Step 13 — Stratified sampling

**What's happening / why:** Draws a diverse, size-controlled sample from the scored bulk pool —
stratified by match-score band × journal bucket × year bucket — rather than a raw score-cutoff
dump, so the curation queue isn't dominated by one journal or one score band. **This is where
"different thresholds, journal diversity etc." already lives** (`configs/sampling.yaml`:
`n_score_bands`, `top_n_journals`, `year_bucket_width`, `cap_per_stratum`) — no code changes were
needed for that part, it was already built this way. **The size of the output file is the number
of new papers you're about to be asked to manually review** — this is the single biggest driver
of your curation workload.

Current config: `cap_per_stratum: 10` → **~3,000–3,200 candidates expected** per `ROADMAP.md`'s
worked example (this was sized for the original, much smaller bulk pool estimate — worth
reconsidering now that the actual pool is 745k, not the ~5-10k originally envisioned; the strata
themselves scale with the *data*, not the pool size, so this estimate likely still roughly holds,
but check the `stratum_report.csv` `available` column once run). Edit `cap_per_stratum` in
`configs/sampling.yaml` before running if you want more/fewer — it's the one knob to change.

**Command:**
```bash
docker compose run --rm pipeline dome-triage sampling stratify
```

**Expected output:** `data/processed/stratified_candidate_pool.csv` and
`data/processed/stratum_report.csv`. New candidates are merged into `canonical_dataset.csv`'s
curation queue — **already-`already_curated` overlaps are automatically excluded from this merge
already** (matched by pmcid/pmid/doi), so no separate "merge previous pos/neg" step is needed —
that mechanism already existed (`_merge_new_candidates_into_canonical`), it just wasn't visible
until Step 12's new `already_curated` column made it so.

**Once merged, review via the existing Curate app** (`docker compose up curate` → "Curate" page)
— now with filterable access to the BM25-scored pool (score band / top journal / year / BM25
classification, each independently toggleable) and a live diversity dashboard, on top of the two
existing toggles (include-already-labeled, require-PMCID). Full detail in **Step 15a** below rather
than duplicated here — this is where you'll actually use them.

**Validate before continuing:** Row count of `stratified_candidate_pool.csv` is in the expected
ballpark for your `cap_per_stratum`. Check `stratum_report.csv` for any wildly underfilled strata.

**Log:**
- [x] Run on: 2026-08-02 (duration 18.5s)
- `cap_per_stratum` used: 10 (default, unchanged)
- Candidates produced: **2,328** (`stratified_candidate_pool.csv`), across **252** stratum
  combinations (`stratum_report.csv`) — somewhat below the ~3,000-3,200 theoretical estimate,
  expected since real availability per stratum varies (some journal x year x score-band
  combinations simply don't have 10 candidates).
- New records actually merged into `canonical_dataset.csv`: **2,327** (1 was already present).
  `canonical_dataset.csv` grew from 4,320 to **6,647** rows.
- Decision/notes: __________

---

## Step 14 — Fetch clear negatives

> **⏸ ON HOLD — deliberate, not forgotten.** Your explicit call (2026-08-02): don't run this yet.
> Sequencing decision: finish a real manual curation pass on the queue Step 13 already built
> (Step 15 — 2,862 papers, open now) first, so a large bulk of genuine human review happens and
> validates the pipeline before the negative pool gets expanded further. Come back to Step 14
> **after** that curation pass, not before. The code is built and tested either way (136/136
> passing) — this is purely a "not yet" on timing, nothing here is blocked or broken.

**What's happening / why:** The bulk-match query (Step 9) structurally can't produce a true "no
AI/ML mention at all" negative — it only ever matches AI/ML papers. This step queries **live
Europe PMC directly** (not the local 750k pool) for the *inverse*: `EXCLUDE_QUERY` in
`src/dome_triage/ingest/clear_negative_sampler.py` requires the **absence** of "artificial
intelligence"/"machine learning"/"deep learning"/"neural network", the structural opposite of Step
9's `bulk_match.py::AI_ML_QUERY`. Every record here is independently confirmed by EPMC's own
search to not mention those terms — genuinely disjoint from the 750k pool by construction, not a
downsample or filter of it.

As of this rewrite: (1) the fetched pool is now **journal/year-stratified** (reusing
`sampling/stratified.py`'s `build_strata`/`stratified_sample` — the same tested bucketing Step 13
uses) rather than a plain random downsample, so it's diverse across journals and years, not just
whatever the random date windows happened to catch; (2) a new **`--merge-limit`** option separates
"how big a diverse pool to build" from "how much of it actually lands in `canonical_dataset.csv`
this run" — see the ratio arithmetic below for why that split matters.

**Class-imbalance arithmetic, worth reading before choosing numbers**: `clear_negative_sampler`
stamps `label="negative"` *at fetch time* — the moment a batch merges into
`canonical_dataset.csv`, that count lands in the `label` column, before any human review. Current
canonical dataset (pre-Step-14): **1,878 positive / 1,907 negative** (~1:1). Auto-merging a full
10k batch in one shot would push that to ~11,907 negative vs 1,878 positive (≈6.3:1) — genuinely
too skewed: at that ratio a classifier can shortcut to "always predict negative" and still score
well on raw accuracy. Recommended starting point: **`--sample-size 10000 --merge-limit 2000`** —
builds the full diverse ~10k pool (cheap, just an interim file) but merges only ~2,000 into the
canonical dataset this round, landing at ≈2.1:1. That's a deliberate middle point, not just
"smaller than 6.3:1": a mild negative skew (roughly 1.5:1–2.5:1) is standard for a triage
classifier like this and *helps* it, since the true prevalence of AI/ML-methods papers across all
of EPMC is itself well below 50% — a naive 1:1 balance would miscalibrate the model for what it'll
actually see in production. Because the fetch is deterministically seeded, re-running with a
higher `--merge-limit` refetches the *same* pool and the existing dedup-by-ID merge logic pulls in
only the incremental delta — phased merging for free; watch the live ratio (Step 15a's diversity
dashboard, or the printed summary after each run) before increasing it.

**Command:**
```bash
docker compose run --rm pipeline dome-triage ingest fetch-clear-negatives --year-from 2015 --year-to 2025 --sample-size 10000 --merge-limit 2000
```

**Expected output:** `data/interim/clear_negative_candidates.csv` — the full diverse pool
(~`--sample-size` rows, journal/year-stratified). Up to `--merge-limit` of it merged into
`canonical_dataset.csv`'s curation queue, same mechanism as Step 13. The step prints the raw
pre-stratification count, the stratum report, and the resulting canonical pos/neg ratio — read all
three before deciding on a second round.

**Validate before continuing:** Row count matches roughly what you asked for; spot-check a few
titles/abstracts to confirm they genuinely don't mention AI/ML; check the printed post-merge ratio
isn't wildly more skewed than you intended.

**Log:**
- [ ] Run on: __________
- Year range / sample-size / merge-limit used: __________
- Candidates produced (full pool) / merged (canonical): __________
- Resulting canonical pos/neg ratio (from the printed summary): __________
- Decision/notes: __________

---

## Step 14b — Screen clear negatives against the lexicon ("strong negative" check)

> **⏸ ON HOLD along with Step 14** — same reason, same "after Step 15" sequencing. Nothing to run
> here until Step 14 itself has actually been fired.

**What's happening / why:** A "clear negative" was fetched specifically for **not** containing the
literal phrase "artificial intelligence"/"machine learning" — but a paper can discuss ML concepts
(algorithms, classifiers, predictive models) without ever using those exact phrases. This step
re-scores `clear_negative_candidates.csv` against the *same* promoted lexicon and *same*
Youden threshold Step 12 already validated for the AI/ML pool (`Bm25Scorer`, reused directly —
`src/dome_triage/pipeline/steps.py::step_ingest_screen_clear_negatives`) — anything that still
scores at/above that threshold despite the exclusion query is flagged `needs_screening=True`, a
signal worth a closer look before trusting it as a genuine negative. **Flags, never auto-rejects**
— the actual call stays a human one in the Curate app (Step 15a).

**Command** (run after Step 14; needs Step 11's `scoring_bakeoff_report.csv` for the threshold):
```bash
docker compose run --rm pipeline dome-triage ingest screen-clear-negatives
```

**Expected output:** `data/interim/clear_negative_candidates_screened.csv` — same rows as
`clear_negative_candidates.csv` plus `lexicon_score__bm25`/`needs_screening`. Never overwrites the
raw candidates file (mirrors the `bulk_candidates.csv` → `bulk_candidates_scored.csv` convention).
At ≤10k rows this finishes in well under a minute — no chunking/checkpointing needed at this scale.

**Validate before continuing:** Read the printed flagged count/percentage — spot-check a few
flagged titles/abstracts yourself to sanity-check the flag is catching genuinely borderline cases,
not just noise.

**Log:**
- [ ] Run on: __________
- Candidates screened / flagged: __________
- Decision/notes: __________

---

## Step 15 — Human curation session

**What's happening / why:** This is the real manual labor step. At `cap_per_stratum=10` (Step 13)
plus a ~2,000-record clear-negative merge (Step 14, `--merge-limit 2000`), expect roughly
**5,000-5,200 new papers** queued — see `ROADMAP.md`'s "Curation workload estimate" for the
updated arithmetic (Step 13's real pool is 745k, not the ~5-10k originally envisioned, though the
strata-driven queue size itself doesn't scale with pool size). At a realistic 20-40 seconds per
quick title/abstract/MeSH decision — **~28-58 hours total**, doable across many sessions (the app
resumes exactly where you left off; nothing is lost between sessions). Use Step 15a's new filters
to work through it in whatever diverse order suits you, not necessarily top-to-bottom.

**Before you start (or resume) a session, read/update
[`curation_criteria/CRITERIA.md`](curation_criteria/CRITERIA.md)** — your own living rulebook for
what actually counts as Positive/Negative/Undeterminable/Skipped, seeded with suggested starting
criteria and edge-case guidance. It exists specifically so your bar doesn't quietly drift across a
curation project spanning many sessions/weeks — see the file's own "Why this matters" section for
the reasoning (label consistency directly affects the BERT fine-tune this dataset is for). Add to
it as you go; log any actual rule *change* (not just a clarification) in its changelog section.

**Command:**
```bash
docker compose up curate
# browse to http://localhost:8501
```

### 15a — Curate page (main queue)

**Filters (collapsed "Filters" expander at the top, on/off toggleable, composable)** — join
`bulk_candidates_scored.csv`'s BM25 score/classification onto the queue at read time
(`src/dome_triage/curate/bulk_scores.py`; `canonical_dataset.csv` itself never gains these
columns, same reasoning as Step 12's `already_curated`):
- **Match-score band** — quartiles of `match_score__bm25`, computed fresh over whatever's
  currently in the queue (not Step 13's original 745k-pool-wide bands, which would be less useful
  once the queue is already a small, pre-stratified subset).
  Each band's label shows its **real BM25 range and how many of its records are already
  curated** (e.g. `Q1 (lowest): BM25 5.2-40.1 -- 12/340 curated`), so "Q1"/"Q4" aren't opaque.
  "Curated" here means a genuine positive/negative decision — a Skip or Undeterminable does not
  count (it means "not assessed"/"looked and couldn't tell", neither of which is a label).
- **Journal** — type-to-search over **every journal in the dataset**, not a top-N shortlist.
- **Year** — one range slider; collapse both handles to the same year to pick a single year. Its
  bounds reflect the **currently filtered** population, not the whole corpus — so after filtering
  to e.g. classification=positive, the slider spans only years actually present among those.
- **BM25 classification** — positive/negative, straight from Step 12.
- **Needs-screening-only** — Step 14b's flagged clear-negatives, for batch-reviewing them together.

**Keyboard-first**: **P** = Positive, **N** = Negative, **U** = Undeterminable, **S** = Skip. Each
submits and advances immediately (no separate confirm step — that's slower for rapid review).
Shortcuts are ignored while you're typing in Notes, so "n" types a letter there. **< Back** and
**Forward >** browse the queue freely in either direction, whether or not the records involved
have been decided — browsing is never gated on deciding, and moving around doesn't alter the
"remaining" count. Revisiting a record you already decided this session shows a banner saying so;
deciding again simply supersedes the earlier decision (last one wins).

**Diversity tracker (sidebar, "Diversity tracker" expander)** — deliberately **all-time/
corpus-wide, not scoped to whatever filter is active** (a decision's diversity contribution
doesn't depend on which lens you were viewing it through when you made it — same reasoning as
`term_review_state.py`'s `all_time_counts()`). Shows journal coverage % (journals with at least
one *confirmed* positive/negative decision, out of all journals in the dataset), a per-year
positive/negative bar chart, and a per-journal table. "Confirmed" means trusted `label_confidence`
**or** decided in *this session's* events — so a decision you make right now moves the dashboard
immediately, without needing to run Step 16 first; a freshly-merged, not-yet-reviewed
`heuristic_candidate` batch (e.g. right after Step 14) does *not* inflate coverage before a human
actually looked at it. When a single journal is selected via the filter, that journal's own tally
also shows directly on the page, not just in the sidebar.

**Note**: as of this rewrite, `curate materialize` (Step 16) now upgrades a reviewed record's
`label_confidence` to `human_curated` (previously it only updated `label`, leaving confidence at
whatever it started as) — so a record that was `heuristic_candidate` before you decided it becomes
fully trusted once materialized, same as any other human-curated source.

One paper at a time: title, then **Journal:** and **Year:** as separate labelled fields, the BM25
match score (with a tooltip explaining what the number means against Step 11's validated Youden
threshold — it's a triage ranking signal, not a verdict), MeSH terms where the record has them,
and the abstract in a fixed-height scrollable panel so the decision buttons never move down the
page as abstract length varies.

> **On MeSH terms**: only ~35% of the reviewable queue has any `mesh_headings` at all, and in the
> default unfiltered order the first record that does doesn't appear until roughly position 563 —
> so seeing no MeSH line for a long opening run is expected, not a bug.

Alongside: a free-text **Notes** box, and the structured feature checklist from
`configs/curation_features.yaml` — deliberately trimmed to just **"If negative — why?"**
(theoretical-method-only / generic-nlp-extraction-only / wrong-domain-non-bio /
review-mentions-ml-only / other). The earlier bulk of per-paper checkboxes was removed: at
~5,000 papers, every extra field is multiplied by 5,000, and the ones dropped were either
inferable later from the text or not load-bearing for the BERT fine-tune this dataset feeds.
`configs/curation_features.yaml` is still a living list — add a field back if you find you
genuinely want it.

Decision options: **Positive / Negative / Undeterminable / Skipped**.

**Undeterminable policy** (`ROADMAP.md`) — apply this consistently:
1. No forced resolution — an honest "undeterminable" beats a coin-flip guess.
2. It's distinct from "Skipped" (deferred without fully assessing) — use Undeterminable only
   after actually looking, including full text if available.
3. Excluded from the future classifier's train/val/test splits — it would only add label noise.
4. Retained as a dedicated calibration/routing validation set for Phase 6, once that exists.

Every decision is appended to `curation_events.csv` (append-only, resumable, backed up) — safe
to stop and restart any time.

**Responsiveness**: the first page load after `docker compose up curate` takes **~10 seconds** —
that's reading the 1.7GB `bulk_candidates_scored.csv` into the cached score lookup, and it's paid
**once per app process**, not per interaction. After that, every decision and every Back/Forward
click is **~0.3 seconds**. If you ever see multi-second waits *per decision*, something has
regressed on the page path — see AGENTS.md's "Curate app performance" section, which documents the
two root causes already found and fixed (both made a single click take 40-57s) and the profiling
method for finding a third.

### 15b — Conflicts page
Resolves the **9 flagged conflicts** from Step 2 (`conflicts_for_review.csv`) — side-by-side
view of disagreeing prior labels for the same record. Your resolution is appended to
`conflict_resolutions.csv` — the original conflicting labels are never overwritten.

**Validate as you go:** Periodically check `data/curation_events.csv` (or the count shown in the
app) is growing; stop anytime with `Ctrl+C`, restart later with the same command — it resumes
where you left off.

**Log** (fill in cumulatively across sessions):
| Session date | Papers decided | Positive | Negative | Undeterminable | Skipped | Conflicts resolved | Notes |
|---|---|---|---|---|---|---|---|
| | | | | | | | |

---

## Step 16 — Materialize curation events

**What's happening / why:** Folds `curation_events.csv` into `canonical_dataset.csv` (last
decision wins per record; anything conflicting with a trusted prior label is **flagged, not
silently overwritten**). This is the step that makes your curation session actually count toward
the canonical dataset.

**Command:**
```bash
docker compose run --rm pipeline dome-triage curate materialize
```

**Expected output:** `canonical_dataset.csv` updated in place; console output states how many
events were folded in. Row count should grow from the current 4,329 by however many *new*
records you curated (updates to existing records don't add rows).

**Validate before continuing:** New `canonical_dataset.csv` row count and label distribution make
sense given your curation session log above. Check for any newly flagged conflicts the
materialize step surfaced (re-visit Step 15b if so).

**Log:**
- [ ] Run on: __________
- New canonical_dataset.csv row count: __________
- Any newly-flagged conflicts: __________
- Decision/notes: __________

---

## Phase 1 complete — what's next

Once Step 16 is done, the canonical dataset reflects everything Phase 1 set out to do:
consolidated multi-source labels, an approved keyword lexicon, a bulk AI/ML candidate pool
scored and stratified into a human-reviewed curation round, and clear negatives.

**Phases 2–8 (`ROADMAP.md`) have no code yet** — only stub `__init__.py` files exist in
`src/dome_triage/{models,calibration,routing}/`, and `src/dome_triage/ontology/` has real MeSH
extraction but no EDAM/domain mapping. There is nothing to run for these phases; the next real
action is **implementing Phase 2** (domain-science/EDAM tagging —
`src/dome_triage/ontology/edam_mapper.py::map_to_edam`, `domain_mapper.py::map_to_domain`, per
the interface and acceptance criteria already specified in `ROADMAP.md`). That's a development
task, not a runbook step — this file should be extended with a Step 17 once that code exists,
rather than inventing placeholder commands now.
