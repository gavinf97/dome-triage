# Roadmap

Phase 0-1 (repo scaffold, data consolidation, curation app, keyword extraction, bulk candidate
construction, structured curation) is implemented. Phases 2-8 below are specified — interfaces
and acceptance criteria are fixed so later work slots in without redesigning what's already
built — but not implemented yet.

## Human-in-the-loop checkpoint map (Phase 1)

Which steps are fully automated, which produce a *candidate* file that isn't trusted until a
human looks at it, and exactly what gets reviewed where:

**Sequencing note (2026-08-02):** rows #7/#7b (clear negatives) are built and tested but
deliberately **on hold** — the plan is to complete a real manual curation pass on row #6's queue
first (validating the pipeline via a large bulk of genuine human review), then come back to
expanding the negative pool. See `STEPS_Progress.md` Step 14/14b for the live status.

| # | Command | Automated output | Human reviews via | Reviewed/approved output |
|---|---|---|---|---|
| 1 | `ingest load-sources` → `dedupe consolidate` | `canonical_dataset.csv` | Conflicts page (only flagged conflicts need a fresh look — the rest were already human-labeled in prior curation rounds) | `conflict_resolutions.csv` |
| 2 | `keywords tfidf`/`keybert`/`build-lexicon` | `keyword_lexicon_candidates.csv` (tens of thousands of candidate terms) | `keywords lexicon-stats` (pick a threshold from real counts) + Keyword Review page — one term at a time, Positive/Negative/Irrelevant (not locked to whichever candidate pile surfaced it), plus a manual "add a term" path for anything TF-IDF/KeyBERT never extracted | `keywords materialize-lexicon` → `keyword_lexicon.csv` (positive) + `keyword_lexicon_exclusionary.csv` (negative) |
| 2b | `keywords seed-additional-terms` (curated ML/AI + non-methods-pubtype terms, `src/dome_triage/keywords/curated_terms.py`) → `keywords suggest-final-lexicon` (explainable cleanup) | `keyword_lexicon_added_positive/negative.csv`, then `keyword_lexicon_suggested_final.csv` + `keyword_lexicon_cleanup_log.csv` | Human reads the cleanup log (every removal/flag has a plain-English reason) | Not auto-promoted to row 2's `keyword_lexicon.csv` — a deliberate separate decision |
| 3 | `bulk-match fetch --year-from Y1 --year-to Y2` (one call, e.g. 2000–2026; still one EPMC query per year internally, checkpointed/resumable) | per-year raw EPMC query cache + `bulk_match_summary.csv` (AI-only/ML-only/combined-deduplicated counts, dated) | Not reviewed individually — sanity-checked in aggregate (row counts, field completeness, the printed count breakdown) | `bulk-match build-candidates` → `bulk_candidates.csv` |
| 4 | `keywords scoring-bakeoff` | comparison report (`scoring_bakeoff_report.csv`) | Human reads the report and picks the winning scorer(s) — a real decision point | recorded choice (used as `--scorer`) |
| 5 | `keywords score-bulk-match --scorer <chosen>` | `bulk_candidates_scored.csv` (`match_score` per record) | Not reviewed directly — this is what the stratified sample is drawn from | — |
| 6 | `sampling stratify` (human sets `cap_per_stratum` first) | `stratified_candidate_pool.csv` — **this file's size is the number of new papers needing manual review** | **Curate app** (`docker compose up curate`) — one paper at a time: positive / negative / undeterminable / skipped, plus structured feature flags, MeSH shown for context; filterable by BM25 score band/journal/year/classification, with a live diversity dashboard | Folded into `canonical_dataset.csv` via `curate materialize` (also upgrades `label_confidence` to `human_curated` on a clean decision) |
| 7 | `ingest fetch-clear-negatives --sample-size N --merge-limit M` (live EPMC query, the structural inverse of #3's AI/ML query — genuinely disjoint from the 750k pool, not derived from it; journal/year-stratified; `--merge-limit` phases how much lands in the canonical dataset per round to avoid skewing its pos/neg balance) | `clear_negative_candidates.csv` (full diverse pool) | Same Curate app queue, tagged `source_name=clear_negative_sampler` | Same as #6 |
| 7b | `ingest screen-clear-negatives` — re-scores #7's output against the *same* lexicon/threshold #5 uses; a "clear negative" that still scores high despite the exclusion query gets flagged | `clear_negative_candidates_screened.csv` (`needs_screening` column) | Curate app — flagged records show an inline warning + a "needs-screening-only" filter to batch-review them together | Same as #6 (the flag itself never auto-rejects; the decision is still human) |

Everything from Phase 3 onward follows the same pattern: automated step produces a report or
artifact, human reviews it at a named decision point (picking the winning model from a bake-off
report, setting calibration thresholds from a reliability diagram, spot-checking a precision
sample from the full scan) before the next step proceeds — nothing auto-promotes silently.

## Curation workload estimate

Steps #6, #7, and #7b above are where the real manual labor lives, and its size is directly
controlled by config, not fixed by the code. Updated against the real, run pool (Step 9-10's bulk
pool turned out to be **744,647 records**, not the ~5-10k originally envisioned when this estimate
was first drafted — the strata themselves scale with the *data's* diversity, not the pool's row
count, so the arithmetic below still roughly holds, but it's worth rechecking `stratum_report.csv`
after a real run rather than trusting the estimate blindly):

- Strata: ~4 match-score bands × ~16 journal buckets (top 15 + "other") × ~5 year buckets
  (5-year bins) ≈ **320 stratum combinations** (`configs/sampling.yaml`).
- `cap_per_stratum` is the single knob: cap=5 → up to ~1,600 candidates queued; cap=10 → up to
  ~3,200; cap=20 → up to ~6,400 (actual totals typically land somewhat below the theoretical max).
- Suggested starting point for a first pass: **cap=10 (≈3,000-3,200 candidates from the
  AI/ML-matched pool) + `--sample-size 10000 --merge-limit 2000` clear negatives (≈2,000 merged
  this round, out of a ~10k diverse pool built for later rounds)** — roughly **5,000-5,200 new
  papers**, replacing the earlier blanket "1,500-2,000 clear-negative" estimate now that the
  clear-negative step is deliberately phased (see Step 14 in `STEPS_Progress.md` for the full
  class-imbalance arithmetic behind the 2,000 figure). At a realistic 20-40 seconds per quick
  title/abstract/MeSH decision in the app, that's very roughly 28-58 hours of curation, doable
  across many sessions (the app resumes exactly where it left off).
- Step 7b (screening) adds negligible extra *volume* — it flags a subset of #7's own candidates
  for closer attention, it doesn't queue additional papers.
- Not a commitment — `cap_per_stratum` and `--merge-limit` are the two numbers to change for a
  second pass, once the live pos/neg ratio (visible in the Curate app's diversity dashboard) says
  it's time.

## Phase 0 — Repo scaffold ✅

Docker, README, AGENTS.md, CC BY 4.0 license, GitHub remote, CLI skeleton, config system.

## Phase 1 — Data consolidation, curation, keyword extraction & bulk candidate construction ✅

- Consolidates the 7 existing labeled-data sources (across `DOME_Top_Curate`,
  `DOME-Copilot-Data-Analysis`, `EBI_Search_DOME`) into one canonical dataset with full
  provenance and conflict-flagging (`src/dome_triage/dedupe/`).
- Dockerized Streamlit curation app porting the proven YES/NO/Skip/resume/backup pattern from
  `DOME_Top_Curate/curation.ipynb`, extended with a genuine fourth **Undeterminable** decision
  (see "Undeterminable handling policy" below), MeSH headings shown for context, a
  config-driven structured feature checklist (`configs/curation_features.yaml` — a living
  checklist, not a fixed schema), and a conflict-resolution page (`src/dome_triage/curate/`).
  **Queue now excludes already-trusted prior labels by default** (`label_confidence in
  {human_curated, registry_confirmed}`, `curate/state.py::CurationSession`'s
  `include_already_labeled`/`require_pmcid` toggles) — before this fix the queue had no such
  filter at all, so a fresh session would have presented every already-curated record (~4,320,
  from `DOME_Top_Curate` etc.) for review alongside genuinely new bulk-matched candidates.
  **Filterable + diversity-tracked** (`curate/bulk_scores.py`, extended `CurationSession`): the
  queue can be filtered by BM25 match-score band, top journal, year range, and BM25
  classification (each independently toggleable, joined from `bulk_candidates_scored.csv` at read
  time without ever adding those columns to `canonical_dataset.csv`'s own schema), plus a live
  "Diversity tracker" sidebar showing journal coverage % and per-journal/per-year positive/negative
  counts — deliberately all-time/corpus-wide, not scoped to the active filter, and live-updating
  from this session's in-memory decisions even before `curate materialize` runs. Also flags Step
  14b's "needs screening" clear-negative candidates inline. `curate materialize` now upgrades a
  reviewed record's `label_confidence` to `human_curated` on a clean decision (previously left it
  at whatever it started as, e.g. `heuristic_candidate`, even after a human reviewed it).
- TF-IDF + KeyBERT keyword extraction producing a scored keyword lexicon, seeded from
  `MLit-Triage-Nextflow/categorized_terms.csv`, with a `lexicon-stats` threshold tool and a real
  human review checkpoint (`src/dome_triage/keywords/`, `curate/term_review_state.py`,
  `curate/pages/3_Keyword_Review.py`): every term gets one of three final decisions — positive,
  negative (exclusionary), or irrelevant — independent of which candidate pile surfaced it, plus
  a manual-entry path for terms TF-IDF/KeyBERT never extracted at all. Validated with a first real
  curation round (500 decisions: 314 positive / 5 negative / 181 irrelevant).
- **Exclusionary lexicon** (`keyword_lexicon_exclusionary.csv`): the negative tail of
  `discriminative_score` — terms disproportionately common in the negative/rejected corpus,
  reviewed the same way as the positive lexicon — subtracted as a penalty by
  `Bm25Scorer`/`TfidfCosineScorer`/`WeightedSumScorer` (`src/dome_triage/keywords/scoring.py`,
  `--exclusionary-weight`). Grounded in a real architectural finding: BM25 and TF-IDF-cosine both
  flatten every lexicon term to unigram tokens before scoring, so a phrase like "machine learning"
  gives no extra precision over the bare unigrams "machine"/"learning" — the exclusionary lexicon
  is what actually lets a necessary-but-generic word (e.g. "forest") get down-weighted without
  losing the specific phrase ("random forest") that still needs it.
- **Curated term additions + explainable cleanup** (`src/dome_triage/keywords/curated_terms.py`,
  `lexicon_cleanup.py`; `keywords seed-additional-terms` / `keywords suggest-final-lexicon`): a
  version-controlled batch of well-known ML/AI vocabulary (supervised/unsupervised algorithms,
  generative model terms, agentic/LLM terms, a small set of flagship biodata-type terms) and
  non-methods publication-type negative terms (review, commentary, editorial, systematic review,
  etc.), added as a separate tier — never merged directly into the human-curated lexicon. A
  rule-based (not black-box) cleanup combines it with the curated lexicon into a reviewed
  "suggested final" lexicon: exact-duplicate removal, redundant-unigram-subsumed-by-a-longer-phrase
  removal (with a reviewed exception allowlist for specific standalone abbreviations like `svm`/
  `cnn`/`xgboost`), and cross-list tension flagging (a negative unigram overlapping a positive
  phrase's token is kept, never silently removed, but logged with which phrase(s) it dampens).
  Every action logged to `keyword_lexicon_cleanup_log.csv`; nothing auto-promotes to production.
- **Bulk blunt-match candidate construction** (`src/dome_triage/ingest/bulk_match.py`): queries
  all of Europe PMC for `"artificial intelligence"` OR `"machine learning"` (`resultType=core`),
  capturing full metadata (title/abstract/authors/journal/year/DOI/PMID/PMCID/MeSH headings/pub
  types/open-access/author keywords) in one pass, no separate enrichment. `bulk-match fetch
  --year-from --year-to` fetches an entire year range (e.g. 2000–2026) in a single invocation —
  still one checkpointed, resumable EPMC query per year internally, with live per-year terminal
  progress, but no longer manually re-triggered per year. Also reports a genuine AI-only/
  ML-only/combined-deduplicated hit-count breakdown for the requested range via three cheap
  count-only queries (`EpmcClient.count`, pageSize=1, `resultType=idlist` — no second full-metadata
  fetch), logged with a run date to `bulk_match_summary.csv`. `configs/sources.yaml`'s
  `epmc.page_size` is 1000 (Europe PMC's documented cursorMark-pagination max) to minimize HTTP
  round-trips for a multi-decade fetch.
- **Relevance-matching bake-off** (`src/dome_triage/keywords/scoring.py`,
  `scoring_bakeoff.py`): three scorers (weighted-sum, BM25, TF-IDF cosine) empirically compared
  against the already-known-labeled records before any is trusted on the unlabeled bulk pool —
  live-verified result: BM25 and TF-IDF-cosine (AUROC ≈0.76-0.77) both substantially outperform
  naive weighted-sum (AUROC ≈0.67), a genuine empirical finding, not an assumption.
- **Stratified sampling** (`src/dome_triage/sampling/`): match-score band × journal bucket ×
  year bucket, capped per stratum, feeding the curation queue with a diverse, sized-to-fit set
  rather than a raw score-cutoff dump.
- **Clear-negative sampler** (`src/dome_triage/ingest/clear_negative_sampler.py`): a **live Europe
  PMC query** excluding AI/ML terms — the structural inverse of the bulk-match query (row 3 of the
  checkpoint map above), genuinely disjoint from the 750k pool, not derived from it — since
  bulk-match structurally cannot produce a true "no AI/ML mention at all" negative. Random
  narrow date-window sampling, now **journal/year-stratified** (reuses
  `sampling/stratified.py::build_strata`/`stratified_sample`) rather than plain-random, with a
  `--merge-limit` option that phases how much of a diverse fetched pool actually lands in
  `canonical_dataset.csv` per run — deliberate, since these candidates are stamped `label=
  "negative"` at fetch time and an unphased merge could swing the dataset's raw pos/neg balance
  sharply negative before any human review (see `STEPS_Progress.md` Step 14 for the arithmetic).
  **Strong-negative screening** (`step_ingest_screen_clear_negatives`, Step 14b): re-scores the
  fetched pool against the same promoted lexicon/threshold the AI/ML pool uses, flagging (never
  auto-rejecting) any candidate that scores suspiciously high despite the exclusion query.
- **Provenance ledger** (`src/dome_triage/provenance.py`): every step appends a record to
  `data/provenance.jsonl` (git commit, exact inputs/outputs with row counts and hashes, params,
  duration) and prints the same as a human-readable summary — no generated file exists without
  an audit trail of what produced it.

## Undeterminable handling policy

The curation app's fourth decision option, "Undeterminable," means a curator looked carefully
(including at any available full text) and genuinely could not decide — distinct from `skipped`
(deferred without fully assessing).

1. **No forced resolution at labeling time.** An honest "undeterminable" beats a coin-flip
   pos/neg — forcing a decision on genuinely ambiguous cases injects label noise.
2. **One cost-bounded second pass, only for a prioritized subset**: for undeterminable records
   without full text fetched yet, pull it (`dome-triage fulltext fetch`) and give the curator
   one more look — but only for records plausibly high-value to get right (recent, relevant
   journal, high citation count). A residual genuinely-irresolvable fraction is expected and normal.
3. **Excluded from the classifier's train/val/test splits** (see Model Evaluation Standards
   below) — they'd only add label noise to a binary classifier.
4. **Retained as a dedicated calibration/routing validation set.** Once Phase 6's confidence
   router exists, this human-labeled "genuinely hard" set is the natural benchmark for checking
   whether the router correctly flags these as "needs human review" rather than confidently
   guessing wrong — a direct, methodologically clean link between curation output and model
   validation.

## Model Evaluation Standards

Grounded in DOME's own schema criteria (`dome-skill/references/field_extraction_guide.md` — the
real DOME schema v2.0.0 field-by-field guide), not generic ML advice. dome-triage self-applies
the DOME standard to its own model development, since it exists to check that other papers meet
it. Every future classifier phase (baseline, Bioformer, LLM) must meet these:

- **Splits (DOME D3/D4)**: `data/processed/dataset_splits.csv` (record_id → train/val/test)
  decided once, early, stratified by label × journal_bucket × year_bucket × match_score_band,
  e.g. 70/15/15, built only from records with a definitive `positive`/`negative` label. The test
  split is sealed — never touched for tuning. `undeterminable` records are excluded from all
  three splits (see policy above) and held out as a separate calibration/routing validation set.
- **Leakage checks (D3)**: beyond dedup-by-`canonical_key`, an explicit check for cross-split
  near-duplicates (e.g. a preprint and its later published version), with anything found routed
  to a review file rather than silently dropped.
- **Per-model reporting (O1-O8, M1-M4)**: a `model_card.json` per trained model recording
  algorithm + final hyperparameters, features/encoding, regularization + overfitting/underfitting
  evidence (train-vs-val curves), parameter count, compute duration/hardware (feeding
  `compute_spend_log.csv`), output type, and an interpretability characterization.
- **Per-evaluation reporting (E1-E5)**: metrics reported, the exact protocol (fixed held-out
  split, stated explicitly), comparison against *both* a naive majority-class baseline *and* the
  previous simpler model, and statistical confidence (bootstrap CI on the test set; McNemar's
  test between model variants where applicable).
- **Input-condition consistency**: every model is trained/evaluated primarily on
  title+abstract+journal+year+metadata — the same input it will actually receive for the vast
  majority of the 40M-record full-scan target (Phase 7) — not skewed toward the subset of
  records that happen to have full text. Full text is used only where the uncertain-tier
  re-evaluation design calls for it.

## Phase 2 — Domain-science / EDAM tagging (MeSH already captured)

**Purpose:** MeSH headings are already captured directly from Europe PMC metadata at ingest time
(Phase 1's `bulk_match.py` + `ontology/mesh.py`) — no inference needed for that layer. This
phase adds a coarse domain-science label (e.g. genomics vs. environmental science vs. clinical)
and optional EDAM concept mapping (topic/operation/data-type) on top of the MeSH headings
already present, so the registry can be filtered by application domain later.

**Compute tier:** laptop CPU (embedding similarity against a small ontology is cheap).

**Interface:** `src/dome_triage/ontology/edam_mapper.py::map_to_edam(text: str) ->
list[EdamMatch]` where `EdamMatch = {concept_id, label, score}`. A parallel
`domain_mapper.py::map_to_domain(record) -> list[DomainMatch]`, preferring the MeSH headings
already on the record over inferring tags from scratch — only fall back to
embedding-similarity-against-EDAM-definitions when no usable MeSH tag exists. All model-suggested
tags are proposals for human confirmation via a curation-app page, not auto-applied.

**Acceptance criteria:** ≥80% of known positives receive at least one EDAM tag above threshold;
face-validity review on a sample of 50 tagged records.

## Phase 3 — Baseline classifier

**Purpose:** a cheap, fast reference model (TF-IDF + logistic regression / SGD) to validate
dataset quality and set the floor that heavier models must beat before investing further compute.

**Compute tier:** laptop CPU.

**Interface:** all classifiers (this and later ones) implement the same protocol:
```python
class Classifier(Protocol):
    def predict(self, title: str, abstract: str, metadata: dict) -> Prediction: ...
# Prediction = {label: "positive"|"negative", confidence: float, rationale: str}
```
`src/dome_triage/models/tfidf_logreg.py` is the first implementation.

**Acceptance criteria:** per Model Evaluation Standards above — reported against the fixed held-out
split, compared to a naive majority-class baseline, with the required O/M/E fields documented.

## Phase 4 — Bioformer / PubMedBERT fine-tune

**Purpose:** a domain-pretrained transformer encoder for the language nuance a bag-of-words
baseline can't capture (e.g. distinguishing "we developed a CNN for X" from "prior work used a
CNN for X, but we use linear regression").

**Compute tier:** lab NVIDIA GPU first (free). Escalate to paid cloud/TPU only if the lab GPU is
insufficient, with cost estimated and logged in `docs/compute_log.md` before running, respecting
the project's £100 total cap.

**Interface:** `src/dome_triage/models/bioformer.py`, same `Classifier` protocol as Phase 3.

**Acceptance criteria:** per Model Evaluation Standards — beats the Phase 3 baseline on the same
sealed test split, with full O/M/E reporting.

## Phase 5 — LLM bake-off

**Purpose:** empirically compare several LLM backends (not commit to one upfront) — trialling
lightweight LLMs that could scale to the full Europe PMC database using title/abstract/journal/
year/metadata as input — on a shared held-out evaluation sample, to decide whether an LLM is
worth using at all versus Bioformer alone, and if so which one, for the "uncertain confidence"
tier of the routing logic in Phase 6.

**Compute tier:** local Ollama on the lab GPU + one or two cost-efficient cloud APIs, capped by
the project's overall £100 spend limit, cost logged before each paid batch.

**Interface:** `src/dome_triage/models/llm_backend.py::LLMBackend(Classifier)` with one adapter
class per backend (e.g. `OllamaBackend`, `CloudAPIBackend`), plus a `bakeoff.py` harness that runs
every registered backend over the same sample and reports precision/recall/F1, cost-per-1,000
papers, and median latency per backend.

**Acceptance criteria:** per Model Evaluation Standards, plus a written comparison report and a
recommendation for the production routing engine.

## Phase 6 — Calibration + routing

**Purpose:** convert raw model scores into trustworthy probabilities and route papers
automatically based on confidence.

**Compute tier:** laptop CPU.

**Interface:** `src/dome_triage/calibration/calibrate.py::fit_calibrator` (isotonic regression via
scikit-learn's `CalibratedClassifierCV`), `src/dome_triage/routing/router.py::route(prediction,
thresholds) -> {"auto_positive", "auto_negative", "needs_review"}`.

**Acceptance criteria:** a documented reliability diagram; thresholds tuned so
`auto_positive`/`auto_negative` hit a target precision (e.g. ≥95%); `needs_review` items land in
the curation app's queue that Phase 1 already built; validated against the retained
Undeterminable set (does the router correctly flag genuinely hard cases as needing review?).

## Phase 7 — Bulk historical Europe PMC scan

**Purpose:** score the **full** Europe PMC database (not just the AI/ML-prefiltered subset used
to build the training set) using title/abstract/year/metadata (full-text fallback only for the
routed "uncertain" subset) with whichever model wins Phase 4/5.

**Compute tier:** laptop CPU if the production model is non-LLM (ONNX-quantized Bioformer scales
to tens of abstracts/sec on CPU); lab GPU or self-hosted Ollama strongly preferred over a paid API
at this volume, to stay inside budget.

**Interface:** `src/dome_triage/pipeline/bulk_scan.py::run_bulk_scan`, reusing
`src/dome_triage/ingest/epmc_client.py` from Phase 1.

**Acceptance criteria:** full scan completes within the compute/time budget; results land in
`historical_scan_results.csv`; a human-reviewed precision spot-check on a random sample.

## Phase 8 — Daily production pipeline

**Purpose:** an ongoing, near-zero-cost delta scan of new Europe PMC publications, feeding the
classifier and curation queue.

**Compute tier:** laptop CPU / cron — this is the only phase that must run indefinitely, so it
must stay near £0 marginal cost per run.

**Interface:** `src/dome_triage/pipeline/daily_scan.py::run_daily_delta`.

**Acceptance criteria:** completes within a defined time budget; produces a delta report; fails
loudly (not silently) on error.
