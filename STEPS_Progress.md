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

---

## Status snapshot (verified 2026-07-31, updated after Step 8's keyword lexicon curation)

| Phase | State |
|---|---|
| Phase 0 — repo scaffold | ✅ Done |
| Phase 1 — data consolidation → curation | 🟡 Consolidation + keyword lexicon (Steps 1–8d, incl. a real curation round and the 3-tier lexicon system) done; bulk-match, scoring-bakeoff, sampling, clear-negatives, and the paper-level curation session (Steps 9–16) are **not yet run** |
| Phases 2–8 (EDAM tagging, classifiers, calibration, bulk scan, daily pipeline) | ⬜ Not implemented — no code exists yet beyond stub `__init__.py` files. Nothing to run here; see the closing section. |

Canonical dataset right now: **4,329 records** (`data/processed/canonical_dataset.csv`), with
**9 flagged conflicts** awaiting resolution (`data/processed/conflicts_for_review.csv`).

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
**Log:** Present on disk as of 2026-07-31. No provenance entry.

### Step 5 — KeyBERT keyword extraction ✅
**Command:** `docker compose run --rm pipeline dome-triage keywords keybert`
**Output:** `data/interim/keybert_terms.csv`
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
- [ ] Run on: __________
- **AI-mentioning: __________ | ML-mentioning: __________ | Combined (deduplicated): __________**
  (also in `data/processed/bulk_match_summary.csv`, dated)
- Decision/notes: __________

---

## Step 10 — Build bulk candidate pool

**What's happening / why:** Consolidates every year's checkpoint file from Step 9 into one
deduplicated candidate pool, keyed on `pmcid`. **Still needed even though Step 9 is now one
command**, not per-year consolidation you manually trigger — Step 9 still writes one JSONL file
per year internally (for checkpointing/resumability), so something still has to merge those files
into a single pool before scoring/sampling can use it. This step is that merge; nothing about it
changed. It does not need to separately dedupe "AI vs ML" — Step 9's combined query already
returns each matching record exactly once, so any duplication this step removes is purely
cross-year (e.g. a record whose date metadata put it on a year boundary).

**Command:**
```bash
docker compose run --rm pipeline dome-triage bulk-match build-candidates
```

**Expected output:** `data/interim/bulk_candidates.csv` (per `configs/sampling.yaml`'s
`paths.bulk_candidates`).

**Validate before continuing:** Row count roughly matches Step 9's `combined_count` from
`bulk_match_summary.csv`, minus any cross-year duplicates.

**Log:**
- [ ] Run on: __________
- Row count: __________
- Decision/notes: __________

---

## Step 11 — Relevance-scoring bake-off

**What's happening / why:** Empirically compares three scorers (weighted-sum, BM25, TF-IDF
cosine) against the **already-labeled** records (Step 2's canonical dataset) before trusting any
of them to rank the unlabeled bulk pool — a real empirical check, not an assumption.

> **Note:** this step was already run once, on 2026-07-28 (`data/provenance.jsonl` entry,
> `step_name=keywords.scoring-bakeoff`, 213.9s duration), and `ROADMAP.md` records its result:
> BM25 and TF-IDF-cosine (AUROC ≈0.76–0.77) both substantially outperform weighted-sum
> (AUROC ≈0.67). **However, the output file `data/processed/scoring_bakeoff_report.csv` is not
> currently present in `data/`** — re-run it below to regenerate the report and confirm the
> result still holds on your current dataset before picking a scorer for Step 12.

**Command:**
```bash
docker compose run --rm pipeline dome-triage keywords scoring-bakeoff
```

**Expected output:** `data/processed/scoring_bakeoff_report.csv` (3 rows — one per scorer — with
AUROC or equivalent metric per scorer). Takes ~3–4 minutes based on the prior run.

**Validate before continuing:** Read the report. Confirm which scorer(s) win. This is a genuine
decision point — don't rubber-stamp the numbers above without checking your own regenerated
report, since the dataset has likely changed since 2026-07-28.

**Log:**
- [ ] Run on: __________
- Report results (scorer: AUROC): __________
- Scorer chosen for Step 12: __________
- Decision/notes: __________

---

## Step 12 — Score the bulk pool with the chosen scorer

**What's happening / why:** Applies the scorer you picked in Step 11 to every record in the
bulk candidate pool, producing a `match_score` per record. This is what Step 13's stratified
sample gets drawn from.

**Command** (replace `bm25` with whatever you chose in Step 11 — options are `weighted-sum`,
`bm25`, `tfidf-cosine`, or `all`; CLI default if you omit `--scorer` is `weighted-sum`, so don't
omit it):
```bash
docker compose run --rm pipeline dome-triage keywords score-bulk-match --scorer bm25
```

**Expected output:** `data/interim/bulk_candidates_scored.csv` (per
`configs/sampling.yaml`'s `paths.bulk_candidates_scored`), same row count as
`bulk_candidates.csv` plus a `match_score` column.

**Validate before continuing:** Score distribution isn't degenerate (not everything scoring 0 or
identical).

**Log:**
- [ ] Run on: __________
- Scorer used: __________
- Row count: __________
- Decision/notes: __________

---

## Step 13 — Stratified sampling

**What's happening / why:** Draws a diverse, size-controlled sample from the scored bulk pool —
stratified by match-score band × journal bucket × year bucket — rather than a raw score-cutoff
dump, so the curation queue isn't dominated by one journal or one score band. **The size of the
output file is the number of new papers you're about to be asked to manually review** — this is
the single biggest driver of your curation workload.

Current config (`configs/sampling.yaml`): `cap_per_stratum: 10`, ~320 stratum combinations (4
score bands × 15 top journals + "other" × 5 year buckets) → **~3,000–3,200 candidates expected**
per `ROADMAP.md`'s worked example. If that's too many or too few for a first pass, edit
`cap_per_stratum` in `configs/sampling.yaml` before running (it's the one knob to change).

**Command:**
```bash
docker compose run --rm pipeline dome-triage sampling stratify
```

**Expected output:** `data/processed/stratified_candidate_pool.csv` and
`data/processed/stratum_report.csv`. New candidates are merged into
`canonical_dataset.csv`'s curation queue.

**Validate before continuing:** Row count of `stratified_candidate_pool.csv` is in the expected
ballpark for your `cap_per_stratum`. Check `stratum_report.csv` for any wildly underfilled strata
(may indicate a config or data issue, not necessarily a problem).

**Log:**
- [ ] Run on: __________
- `cap_per_stratum` used: __________
- Candidates produced: __________
- Decision/notes: __________

---

## Step 14 — Fetch clear negatives

**What's happening / why:** The bulk-match query (Step 9) structurally can't produce a true "no
AI/ML mention at all" negative — it only ever matches AI/ML papers. This step randomly samples
from narrow date windows *excluding* AI/ML terms, giving the classifier genuine negative
examples later.

**Command** (year range and sample size are your call — README's example below; CLI default
`--sample-size` is 2000 if omitted):
```bash
docker compose run --rm pipeline dome-triage ingest fetch-clear-negatives --year-from 2015 --year-to 2025
```

**Expected output:** `data/interim/clear_negative_candidates.csv` — **~1,500–2,000 candidates
expected** per `ROADMAP.md`'s worked example (with default `--sample-size 2000`). Merged into
`canonical_dataset.csv`'s curation queue, same as Step 13.

**Validate before continuing:** Row count matches roughly what you asked for; spot-check a few
titles/abstracts to confirm they genuinely don't mention AI/ML.

**Log:**
- [ ] Run on: __________
- Year range / sample size used: __________
- Candidates produced: __________
- Decision/notes: __________

---

## Step 15 — Human curation session

**What's happening / why:** This is the real manual labor step. At `cap_per_stratum=10` plus the
clear-negative sample, expect roughly **4,500–5,000 new papers** queued, at a realistic
20–40 seconds per quick title/abstract/MeSH decision — **~25–55 hours total**, doable across many
sessions (the app resumes exactly where you left off; nothing is lost between sessions).

**Command:**
```bash
docker compose up curate
# browse to http://localhost:8501
```

### 15a — Curate page (main queue)
One paper at a time: title/journal/year/MeSH/abstract shown, plus the structured feature
checklist from `configs/curation_features.yaml`:
- Applies ML/AI to empirical data? (bool)
- Proposes a novel algorithm? (bool)
- Primary domain area (genomics / imaging / clinical / environmental / chemistry / other)
- If negative — why? (theoretical-method-only / generic-nlp-extraction-only /
  wrong-domain-non-bio / review-mentions-ml-only / other) — only shown when decision=negative
- Your confidence (low / medium / high)

Decision options: **Positive / Negative / Undeterminable / Skipped**.

**Undeterminable policy** (`ROADMAP.md`) — apply this consistently:
1. No forced resolution — an honest "undeterminable" beats a coin-flip guess.
2. It's distinct from "Skipped" (deferred without fully assessing) — use Undeterminable only
   after actually looking, including full text if available.
3. Excluded from the future classifier's train/val/test splits — it would only add label noise.
4. Retained as a dedicated calibration/routing validation set for Phase 6, once that exists.

Every decision is appended to `curation_events.csv` (append-only, resumable, backed up) — safe
to stop and restart any time.

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
