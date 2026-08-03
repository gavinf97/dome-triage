# dome-triage

A reproducible, Dockerized pipeline for triaging Europe PMC publications as relevant (or not) to the
[DOME registry](https://registry.dome-ml.org) — the community standard for reporting **D**ata,
**O**ptimization, **M**odel, and **E**valuation practices in machine learning applied to the life
sciences.

Europe PMC holds tens of millions of publications. Manually finding the ones that apply an AI/ML
method to biological, medical, or adjacent scientific data — and therefore belong in the DOME
registry — does not scale by hand. This repo builds a triage system to do that: starting from
blunt keyword matching and a growing human-curated dataset, through statistical and semantic
keyword extraction, ontology-grounded tagging, and eventually BERT/LLM-based classification with
calibrated confidence and human-in-the-loop review at every stage that needs it.

## Relationship to prior work

This repo consolidates and builds on several earlier, disconnected efforts in this project family:

| Repo | What it contributed |
|---|---|
| [`DOME_Top_Curate`](../DOME_Top_Curate) | ~3,900 human-curated positive/negative/skipped labels (ipywidgets curation UI), plus ~231 PDFs of confirmed DOME registry entries and ~1,014 candidate-positive PDFs |
| [`DOME-Copilot-Data-Analysis`](../DOME-Copilot-Data-Analysis) | An independent ~1,012/1,012 positive/negative curation round with full text, a 222-PMCID gold set, and working EuropePMC query code |
| [`MLit-Triage-Nextflow`](../MLit-Triage-Nextflow) | TF-IDF/NLP preprocessing code and a DOI→PMCID→full-text fetch pipeline |
| [`Filtered_MLIT_TriageFAIR_OPEN_AI_Paper`](../Filtered_MLIT_TriageFAIR_OPEN_AI_Paper) | The original weighted-keyword-matching relevance scorer that produced the DOME_Top_Curate labels |
| [`EBI_Search_DOME`](../EBI_Search_DOME) | Raw DOME registry review API dump (additional confirmed positives) |
| [`dome-schema`](../dome-schema) | The canonical DOME JSON schema and validator |

None of these talk to each other, and none has ontology mapping or a trained classifier — that's
what this repo is for. See `ROADMAP.md` for the full phase breakdown and current status.

## Key documents

| File | What it's for |
|---|---|
| [`ROADMAP.md`](ROADMAP.md) | Phase plan (0–8), human-in-the-loop checkpoint map, Model Evaluation Standards |
| [`STEPS_Progress.md`](STEPS_Progress.md) | Step-by-step runbook with a live decision log and per-step results |
| [`METHODS_REVIEW.md`](METHODS_REVIEW.md) | Scientific audit of the approach so far + the classifier/tagging model plan |
| [`PREPROCESSING.md`](PREPROCESSING.md) | Every text-preprocessing choice, justified, with known limitations |
| [`SCORING_BAKEOFF_RESULTS.md`](SCORING_BAKEOFF_RESULTS.md) | Full Step 11 relevance-scorer comparison, explained figure by figure |
| [`curation_criteria/CRITERIA.md`](curation_criteria/CRITERIA.md) | Your living rulebook for what counts as Positive/Negative/Undeterminable/Skipped |
| [`AGENTS.md`](AGENTS.md) | Repo conventions: Docker-only execution, testing rules, disk hygiene, Curate-app performance |

## Design philosophy: human-led, fully traceable

This pipeline is built to be run **manually, one step at a time, by a person following along** —
not as a black-box end-to-end automated job. Every command prints what it read, what it's doing
(with a live progress bar for anything slow), and what it wrote, and every generated file is
backed by an entry in `data/provenance.jsonl` recording the exact command, inputs, config, and git
commit that produced it (see `AGENTS.md`). `pipeline run --steps a,b,c` exists as a convenience
for re-running an already-verified chain quickly — it is not the primary way to use this repo.

## Quickstart

Each command below is meant to be run on its own, so you can inspect its output before deciding
on the next one — see `ROADMAP.md`'s "Human-in-the-loop checkpoint map" for exactly what to look
at and where manual curation happens.

```bash
docker compose build

# 1. Consolidate the existing labeled sources
docker compose run --rm pipeline dome-triage ingest load-sources
docker compose run --rm pipeline dome-triage dedupe consolidate
docker compose run --rm pipeline dome-triage fulltext build-manifest

# 2. Build and threshold the keyword lexicon
docker compose run --rm pipeline dome-triage keywords tfidf
docker compose run --rm pipeline dome-triage keywords keybert
docker compose run --rm pipeline dome-triage keywords build-lexicon
docker compose run --rm pipeline dome-triage keywords lexicon-stats   # pick a cutoff from real counts
# ... approve terms above that cutoff via the Streamlit "Keyword Review" page ...

# 3. Bulk blunt-match candidate construction (whole year range in one call -- see ROADMAP.md)
docker compose run --rm pipeline dome-triage bulk-match fetch --year-from 2000 --year-to 2026
docker compose run --rm pipeline dome-triage bulk-match build-candidates

# 4. Pick a relevance-scoring algorithm empirically, then score and sample
docker compose run --rm pipeline dome-triage keywords scoring-bakeoff
docker compose run --rm pipeline dome-triage keywords score-bulk-match --scorer bm25
docker compose run --rm pipeline dome-triage sampling stratify
docker compose run --rm pipeline dome-triage ingest fetch-clear-negatives --year-from 2015 --year-to 2025

# 5. Human curation (http://localhost:8501)
# ... before you start, read/update curation_criteria/CRITERIA.md -- your living rulebook for
#     what counts as Positive/Negative/Undeterminable/Skipped, so the bar stays consistent
#     across a curation project that spans many sessions ...
docker compose up curate
# ... after a curation session, fold decisions back into the canonical dataset ...
docker compose run --rm pipeline dome-triage curate materialize
```

Every command reads its config files from `configs/` by default (override with `--config-dir`).
Every step reads/writes plain CSV/JSONL files under `data/` (gitignored) via paths declared in
`configs/`, so any step can be run, inspected, and re-run independently.

## Status

**Phase 1 is complete through Step 13; manual curation (Step 15) is the active step.**

Where the data stands (verified 2026-08-02):

| | |
|---|---|
| Canonical dataset | 6,647 records |
| Definitively labeled | 3,785 (1,878 positive / 1,907 negative) |
| Curation queue awaiting review | 2,328 |
| Keyword lexicon | 296 positive terms / 18 exclusionary |
| Europe PMC AI/ML bulk pool | 744,647 records, BM25-scored |
| Chosen relevance scorer | `bm25` + exclusionary lexicon (Youden threshold 107.6) |

**Implemented:** repo scaffold, Docker, data consolidation across the existing labeled sources
into one canonical dataset with full provenance and conflict-flagging, a Dockerized Streamlit
curation app (keyboard-driven P/N/U/S decisions, score-band/journal/year/classification filters,
live diversity dashboard, MeSH display, structured feature capture, and a genuine Undeterminable
outcome), TF-IDF + KeyBERT keyword extraction with a threshold tool and human review checkpoint,
bulk blunt-match candidate construction against Europe PMC with full metadata capture (including
MeSH headings), an empirically-validated relevance-scoring bake-off (BM25/TF-IDF-cosine/
weighted-sum), stratified sampling, a clear-negative sampler with strong-negative screening, and a
project-wide provenance ledger.

**On hold by explicit decision:** Steps 14/14b (clear-negative fetch + screening) are built and
tested but deliberately not run yet — the plan is to complete a real manual curation pass first,
then revisit expanding the negative pool. See `STEPS_Progress.md`.

**Not yet built** (specified in `ROADMAP.md`): domain-science/EDAM tagging beyond the MeSH
headings already captured, baseline and BERT/LLM classifiers, probability calibration and
confidence-based routing, the bulk historical Europe PMC scan, and the daily production pipeline.

**Before the modelling phases**, see [`METHODS_REVIEW.md`](METHODS_REVIEW.md) — an audit of the
approach so far (retrieval coverage, the BM25/lexicon scoring mechanism, evaluation validity,
dataset confounds) and the plan for the relevance classifier plus DOME-aligned model-type tagging.
It flags four cheap fixes worth making *before* curating substantially more data.

## License

CC BY 4.0 — see `LICENSE.md`. Matches the license used by `DOME_Top_Curate` and `dome-schema`.
