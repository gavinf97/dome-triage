# Roadmap

Phase 0-1 (repo scaffold, data consolidation, curation app, keyword extraction) is implemented.
Phases 2-8 below are specified — interfaces and acceptance criteria are fixed so later work slots
in without redesigning what's already built — but not implemented yet.

## Phase 0 — Repo scaffold ✅

Docker, README, AGENTS.md, CC BY 4.0 license, GitHub remote, CLI skeleton, config system.

## Phase 1 — Data consolidation, curation app, keyword extraction ✅

- Consolidates the 7 existing labeled-data sources (across `DOME_Top_Curate`,
  `DOME-Copilot-Data-Analysis`, `EBI_Search_DOME`) into one canonical dataset with full
  provenance and conflict-flagging (`src/dome_triage/dedupe/`).
- Dockerized Streamlit curation app porting the proven YES/NO/Skip/resume/backup pattern from
  `DOME_Top_Curate/curation.ipynb`, extended with Uncertain/Close-Negative tags, free-text notes,
  and a conflict-resolution page (`src/dome_triage/curate/`).
- TF-IDF + KeyBERT keyword extraction producing a scored keyword lexicon, seeded from
  `MLit-Triage-Nextflow/categorized_terms.csv`, with a human review checkpoint
  (`src/dome_triage/keywords/`).

## Phase 2 — Ontology / domain-science tagging

**Purpose:** map each record to EDAM concepts (topic/operation/data-type) and a coarse
domain-science label (e.g. genomics vs. environmental science vs. clinical), so the registry can
be filtered by application domain later.

**Compute tier:** laptop CPU (embedding similarity against a small ontology is cheap).

**Interface:** `src/dome_triage/ontology/edam_mapper.py::map_to_edam(text: str) ->
list[EdamMatch]` where `EdamMatch = {concept_id, label, score}`. A parallel
`domain_mapper.py::map_to_domain(record) -> list[DomainMatch]`.

**Design note:** prefer existing metadata the record already carries (Europe PMC / MeSH major
topic headings, where present) over inferring tags from scratch — only fall back to
embedding-similarity-against-EDAM-definitions when no usable existing tag exists. All
model-suggested tags are proposals for human confirmation via a curation-app page, not
auto-applied.

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

**Acceptance criteria:** stratified k-fold CV report (precision/recall/F1) on the canonical
dataset, held as the baseline other models are compared against.

## Phase 4 — Bioformer / PubMedBERT fine-tune

**Purpose:** a domain-pretrained transformer encoder for the language nuance a bag-of-words
baseline can't capture (e.g. distinguishing "we developed a CNN for X" from "prior work used a
CNN for X, but we use linear regression").

**Compute tier:** lab NVIDIA GPU first (free). Escalate to paid cloud/TPU only if the lab GPU is
insufficient, with cost estimated and logged in `docs/compute_log.md` before running, respecting
the project's £100 total cap.

**Interface:** `src/dome_triage/models/bioformer.py`, same `Classifier` protocol as Phase 3.

**Acceptance criteria:** beats the Phase 3 baseline F1 on the same held-out fold.

## Phase 5 — LLM bake-off

**Purpose:** empirically compare several LLM backends (not commit to one upfront) on a shared
held-out evaluation sample, to decide whether an LLM is worth using at all versus Bioformer alone,
and if so which one, for the "uncertain confidence" tier of the routing logic in Phase 6.

**Compute tier:** local Ollama on the lab GPU + one or two cost-efficient cloud APIs, capped by
the project's overall £100 spend limit, cost logged before each paid batch.

**Interface:** `src/dome_triage/models/llm_backend.py::LLMBackend(Classifier)` with one adapter
class per backend (e.g. `OllamaBackend`, `CloudAPIBackend`), plus a `bakeoff.py` harness that runs
every registered backend over the same sample and reports precision/recall/F1, cost-per-1,000
papers, and median latency per backend.

**Acceptance criteria:** a written comparison report and a recommendation for the production
routing engine.

## Phase 6 — Calibration + routing

**Purpose:** convert raw model scores into trustworthy probabilities and route papers
automatically based on confidence.

**Compute tier:** laptop CPU.

**Interface:** `src/dome_triage/calibration/calibrate.py::fit_calibrator` (isotonic regression via
scikit-learn's `CalibratedClassifierCV`), `src/dome_triage/routing/router.py::route(prediction,
thresholds) -> {"auto_positive", "auto_negative", "needs_review"}`.

**Acceptance criteria:** a documented reliability diagram; thresholds tuned so
`auto_positive`/`auto_negative` hit a target precision (e.g. ≥95%); `needs_review` items land in
the curation app's queue that Phase 1 already built.

## Phase 7 — Bulk historical Europe PMC scan

**Purpose:** score the full historical Europe PMC corpus (title/abstract/year/metadata; full-text
fallback only for the routed "uncertain" subset) using the production model chosen after Phase 6.

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
