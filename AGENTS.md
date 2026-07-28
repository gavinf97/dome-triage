# AGENTS.md

Instructions for AI agents (and humans) working in this repository.

## What this repo is

A literature triage pipeline that classifies Europe PMC publications as relevant or not to the
DOME registry. See `README.md` for context and `ROADMAP.md` for the phase plan. This file covers
conventions for making changes here.

## Ground rules

- **Human curation is never bypassed.** Nothing gets promoted to a `positive`/`negative` label
  without either (a) an existing human-curated or registry-confirmed source, or (b) a decision
  recorded through the curation app. Conflicting labels from different sources are never
  silently resolved — they are written to `conflicts_for_review.csv` and surfaced in the
  curation app's Conflicts page for a person to decide.
- **Large data and PDFs are never committed to git.** `data/` is entirely gitignored. Full-text
  PDFs are referenced via `data/fulltext_manifest.csv` (built by `dome-triage fulltext
  build-manifest` from the sibling repos on this machine) rather than copied — see
  `src/dome_triage/fulltext/manifest.py`. `dome-triage fulltext fetch --pmcid ...` re-derives a
  PDF independently via the Europe PMC/NCBI OA API for reproducibility on a machine without
  those sibling repos present.
- **Cost-aware compute.** The whole project has a hard cap of £100 in paid cloud/API spend. Any
  code path that calls a paid API or provisions cloud/TPU compute must estimate and log the cost
  *before* running, and must not proceed past that estimate without explicit confirmation. Default
  to free options (laptop CPU, the lab GPU, local Ollama) wherever they are plausible. Recommended
  compute tier per phase is documented in `ROADMAP.md`.
- **Every pipeline step is independently runnable.** Steps are plain functions in
  `src/dome_triage/pipeline/steps.py`, exposed both as individual `dome-triage <group> <command>`
  CLI subcommands and chained via `dome-triage pipeline run --steps a,b,c`. Do not introduce a
  separate workflow engine (Airflow/Nextflow/Prefect) — this was deliberately ruled out; keep
  steps as plain, debuggable, file-in/file-out functions.
- **No premature abstraction.** This is a research pipeline with a small number of real inputs
  (the 7 source files enumerated in `configs/sources.yaml`, which collapse into 4 loader
  adapters). Don't generalize beyond what those actual sources require.
- **No generated file without a provenance entry.** Every step in `pipeline/steps.py` must call
  `provenance.finish_step(...)` before returning — it appends one line to `data/provenance.jsonl`
  (git commit, exact inputs/outputs with row counts and hashes, params, duration) and prints the
  same as a human-readable summary. If you add a new step, add this call; don't skip it because
  the step "feels minor."
- **No new long-running loop without a progress indicator.** Anything that iterates over more
  than a handful of items with real per-item cost (an API pagination loop, a per-document model
  call) gets a `tqdm` bar — see `ingest/epmc_client.py`'s `search(..., show_progress=True)` and
  `keywords/keybert_extract.py` for the pattern. This project is explicitly human-led: the user
  runs each step manually and needs to see what's happening, not wait on a silent black box.
- **`configs/curation_features.yaml` is a living checklist, not a fixed schema.** Add or remove
  structured curation-feature flags freely as it becomes clearer what actually helps model
  training — don't treat the current set as locked in.

## Repo layout

```
src/dome_triage/
├── cli.py, config.py, schema.py, provenance.py   # Typer app; config loader; CanonicalRecord
│                                                   model; the provenance ledger (see above)
├── ingest/                        # EuropePMC/NCBI querying, ID mapping, source loading,
│                                   # bulk_match.py (bulk AI/ML fetch), clear_negative_sampler.py
├── dedupe/                        # union-find clustering, consolidation, conflict detection
├── fulltext/                      # PDF manifest + fetch fallback
├── keywords/                      # TF-IDF + KeyBERT extraction, lexicon building + lexicon-stats,
│                                   # scoring.py (WeightedSum/BM25/TF-IDF-cosine) + scoring_bakeoff.py
├── sampling/                      # stratified sampling over the scored bulk candidate pool
├── ontology/                      # mesh.py (done — MeSH extraction); EDAM/domain mapping is a stub
├── curate/                        # Streamlit human curation app
├── pipeline/                      # shared step functions + orchestration
└── models/, calibration/, routing/   # STUBS — later phases, see ROADMAP.md
```

## Running things

Everything runs in Docker (`docker compose build`, then `docker compose run --rm pipeline
dome-triage <command>`, or `docker compose up curate` for the UI). See `README.md` Quickstart.
For local (non-Docker) development, install with `pip install -e ".[dev]"` from the repo root —
note `nltk` corpora and the KeyBERT/sentence-transformers model weights are only guaranteed
present inside the Docker image (baked in at build time).

## Testing

`pytest` from the repo root. Tests in `tests/` use small synthetic fixture files in
`tests/fixtures/` that mimic the schema of each real source file — they must never depend on the
multi-GB sibling repos (`DOME_Top_Curate`, `DOME-Copilot-Data-Analysis`, etc.) being present,
since those live outside this repo and aren't guaranteed to exist on every machine or in CI.

## Data provenance

Two complementary mechanisms, both mandatory:

1. **Per-record provenance.** Every record in `canonical_dataset.csv` carries a `sources` field
   listing every contributing source file, its label, and its confidence tier (`human_curated` /
   `registry_confirmed` / `heuristic_candidate` / `unscored`). When adding a new data source, add
   a loader in `src/dome_triage/ingest/source_loaders.py` (reuse one of the existing 4 adapter
   shapes if it fits) and register it in `configs/sources.yaml` — do not hand-merge new data into
   `canonical_dataset.csv` outside the consolidation pipeline.
2. **Per-run provenance.** `data/provenance.jsonl` (see the ground rule above) is the ledger of
   *how every file was generated* — which command, which inputs, which config, when. The two are
   complementary: `sources` tells you where a paper's label came from; `provenance.jsonl` tells
   you how the file containing it was built.
