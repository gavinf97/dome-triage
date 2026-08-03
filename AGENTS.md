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

**Docker only. No local venv, no bare `pip install`, no bare `python`/`pytest` on the host.**
`docker compose build`, then `docker compose run --rm pipeline dome-triage <command>` for every
CLI step, or `docker compose up curate` for the UI. See `README.md` Quickstart. Do not create a
`.venv`/`venv` in this repo and do not run project code against the host Python — `nltk` corpora
and the KeyBERT/sentence-transformers model weights are only present inside the Docker image
(baked in at build time), so a host-Python run will silently diverge from what the pipeline
actually does in the container. If a `.venv`/`venv` directory ever appears here, delete it.

## Docker disk hygiene

**Every `docker compose build` re-run leaves the previous image dangling** (untagged, shows as
`<none>:<none>` in `docker images`/`docker system df -v`) -- the new build takes the `latest` tag,
the old one doesn't get deleted, it just loses its name. At ~6.3GB per `dome-triage-pipeline`/
`dome-triage-curate` image, this accumulates fast across an iterative session: a real incident hit
**14 dangling images (~88GB) and 98% host disk usage** from one session's worth of edit-rebuild
cycles before it was caught. The host also runs other, unrelated Docker Compose projects --
`docker system df -v`'s image list is shared across all of them, not scoped to this repo.

Prune periodically during any session with several rebuilds, and always if disk space gets tight:

```bash
docker container prune -f   # removes stopped containers first (they can pin an image, blocking its removal)
docker image prune -f       # removes dangling (untagged, superseded) images -- safe, never touches a tagged image
```

Both are non-destructive to anything still in use: `image prune` (no `-a` flag) only ever removes
images with no tag and no container referencing them -- a tagged image any project's compose file
points to, running or not, is never touched. Do not reach for `docker image prune -af` (removes
*all* unused images, including other projects' tagged-but-currently-stopped ones) or
`docker system prune -a` without asking first -- the two commands above are the safe default and
are usually enough on their own; note in `docker system df` output that build cache
(`docker builder prune -f`, see below) is a separate, often much larger pool worth checking too.

## Testing

`docker compose run --rm pipeline pytest` from the repo root — not bare `pytest` on the host (see
above). Tests in `tests/` use small synthetic fixture files in `tests/fixtures/` that mimic the
schema of each real source file — they must never depend on the multi-GB sibling repos
(`DOME_Top_Curate`, `DOME-Copilot-Data-Analysis`, etc.) being present, since those live outside
this repo and aren't guaranteed to exist on every machine or in CI.

**`streamlit.testing.v1.AppTest` smoke-checks of the Curate app must point at an isolated
`tmp_path`, never the real `cfg.path("canonical_dataset")`/`cfg.pipeline["curation"]
["events_log"]` paths.** A real incident: a smoke-test session clicked "Positive" against the
live app pointed at real config paths, which genuinely appended a `curator="smoketest"` row to
the actual `data/processed/curation_events.csv` -- indistinguishable from a real decision to
anything downstream (`diversity_stats()`, `materialize_events()`, the curator's own review
queue) until manually spotted and removed. `CurationSession` takes `dataset_path`/`events_path`
directly for exactly this reason -- pass a `tmp_path`-based `canonical_dataset.csv` copy and a
fresh `tmp_path` events file when driving the real page end-to-end, the same as any other test.
The event log's rolling `*_backup.csv` sibling needs the same care -- it is written *before* every
append, so a polluted run leaves fake rows there even after the main file is cleaned. Check both.

## Curate app performance

The Curate app re-executes its whole page script on every interaction (that is just how Streamlit
works), so anything on that path runs tens of times per minute during real curation. Two rules,
both learned from measured incidents that made a single click take 40-57 seconds:

**Never do work that scales with the bulk-score lookup on the page path.** That lookup holds ~2.07
million entries (3 id fields x ~745k bulk-pool rows) while the frame being annotated holds a few
thousand. Anything O(lookup) dominates completely. This bit twice in the same function
(`curate/bulk_scores.py::annotate_bulk_scores`): first as an explicit
`{k: v[0] for k, v in lookup.items()}` rebuild per call (~9-10s), then -- after "fixing" it -- as
`Series.map(lookup)`, which *looks* vectorized but makes pandas build a full 2.07M-element Series
and Index internally before taking the few thousand values wanted (~2.5s). Use plain `lookup.get()`
over the small frame's rows. `tests/test_bulk_scores.py::_NoScanDict` pins this: it raises if
anything walks the whole mapping, so a well-meaning revert to `.map()` fails the suite rather than
silently costing seconds again.

**Don't call `st.rerun()` in a widget callback or click handler.** Streamlit already reruns the
script on any widget interaction; an explicit `st.rerun()` on top forces a *second* full execution
-- exactly doubling the cost -- for no behavioral gain. Mutate state and let the in-flight rerun
render it (see `pages/1_Curate.py`'s Back/Forward handlers, which deliberately sit above
`current_record()` for this reason).

Profile before changing anything here: add temporary `print(..., flush=True)` timers, run the page
headlessly through `AppTest` against the *real* data (with the events log redirected to a tmp dir,
per the Testing rule above), and read the actual numbers. Every performance claim in this section
came from that loop; every wrong guess along the way came from skipping it. Current measured
baseline: ~10s one-time cold start (loading the 1.7GB scored CSV into the cached lookup, paid once
per app process), then **~0.27s per decision or navigation click**.

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
