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
6. Steps 1–7 below are already done — they're logged retroactively from `data/provenance.jsonl`
   and the files already on disk, so the record is continuous from the start even though I
   (Claude) verified them on 2026-07-31 rather than you running them live.

Everything runs via Docker Compose — two services defined in `docker-compose.yml`:
`pipeline` (an interactive shell for one-off `dome-triage <command>` invocations) and `curate`
(the Streamlit human-curation UI on port 8501). No API keys or `.env` file are needed — Europe
PMC is queried unauthenticated, and all configuration is via the YAML files in `configs/`.

---

## Status snapshot (verified 2026-07-31)

| Phase | State |
|---|---|
| Phase 0 — repo scaffold | ✅ Done |
| Phase 1 — data consolidation → curation | 🟡 Half run: consolidation + keyword-lexicon-candidates done; keyword review, bulk-match, scoring, sampling, and the actual curation session are **not yet run** |
| Phases 2–8 (EDAM tagging, classifiers, calibration, bulk scan, daily pipeline) | ⬜ Not implemented — no code exists yet beyond stub `__init__.py` files. Nothing to run here; see the closing section. |

Canonical dataset right now: **4,329 records** (`data/processed/canonical_dataset.csv`), with
**9 flagged conflicts** awaiting resolution (`data/processed/conflicts_for_review.csv`).

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
- [ ] Run on: __________
- Actual output: __________
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

## Step 8 — Keyword Review (human, Streamlit) — NEXT ACTION

**What's happening / why:** 40,756 candidate terms is too many to trust or review one by one.
Step 7's numbers let you pick a defensible cutoff (e.g. `discriminative_score ≥ 0.005` → 81
terms, or `document_frequency ≥ 5` → 112 terms — these bands overlap significantly and are a
reasonable manageable review size). You then approve/reject/edit exactly those candidates in the
UI. Only `review_status=approved` rows become the trusted lexicon.

**Command:**
```bash
docker compose up curate
# browse to http://localhost:8501, open the "Keyword Review" page in the sidebar
```
In the data-editor table: sort/inspect by `discriminative_score` and `document_frequency`, set
`review_status` to `approved` for terms you trust as genuinely discriminative (vs. generic words
like "model"/"learning" that appear high but aren't useful lexicon entries), `rejected` for
noise, leave `pending` for anything you're unsure about (it just won't be included). Click
**"Save reviewed lexicon"**.

**Expected output:** `data/processed/keyword_lexicon.csv` created, containing only the approved
rows; a success message in the UI stating how many terms were saved.

**Validate before continuing:** Open the new `keyword_lexicon.csv` and spot-check that it's not
empty and doesn't contain obvious junk (single letters, stopword-like generic ML terms with no
discriminative value).

Stop the container when done: `Ctrl+C` in the terminal running `docker compose up curate`.

**Log:**
- [ ] Run on: __________
- Threshold(s) used: __________
- Terms approved / rejected / left pending: __________
- Decision/notes: __________

---

## Step 9 — Bulk blunt-match fetch (repeat per year — human-paced)

**What's happening / why:** Queries all of Europe PMC for `"artificial intelligence"` OR
`"machine learning"`, one year at a time, capturing full metadata (title/abstract/authors/
journal/year/DOI/PMID/PMCID/MeSH headings/pub types/open-access/author keywords). This is
**deliberately one command per year** (`ROADMAP.md`, Phase 1) so you can inspect each year's
result before deciding whether to fetch another. **There is no fixed number of years specified
in the docs — that's your call.** A reasonable starting point: fetch one recent year, check the
row count and field completeness, then decide how many more years you actually want feeding the
candidate pool (more years = bigger curation workload later, see Step 13).

**Command (run once per year you choose):**
```bash
docker compose run --rm pipeline dome-triage bulk-match fetch --year 2024
```
Repeat with `--year 2023`, `--year 2022`, etc. as you decide.

**Expected output:** A per-year raw query cache under `data/interim/` (exact filename logged by
the command itself and in `data/provenance.jsonl`). The command prints the row count fetched for
that year.

**Validate before continuing:** Row count is non-trivial (thousands, not zero) and MeSH/journal
fields look populated, not mostly blank.

**Log:**
- [ ] Years fetched: __________ (list each, with row count from output)
- Run on: __________
- Decision/notes on how many years and why: __________

---

## Step 10 — Build bulk candidate pool

**What's happening / why:** Consolidates every year fetched in Step 9 into one deduplicated
candidate pool.

**Command:**
```bash
docker compose run --rm pipeline dome-triage bulk-match build-candidates
```

**Expected output:** `data/interim/bulk_candidates.csv` (per `configs/sampling.yaml`'s
`paths.bulk_candidates`).

**Validate before continuing:** Row count roughly matches the sum of the per-year fetches minus
expected duplicates.

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
