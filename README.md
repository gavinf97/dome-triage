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

## Quickstart

```bash
docker compose build
docker compose run --rm pipeline dome-triage ingest load-sources
docker compose run --rm pipeline dome-triage dedupe consolidate
docker compose run --rm pipeline dome-triage fulltext build-manifest
docker compose run --rm pipeline dome-triage keywords tfidf
docker compose run --rm pipeline dome-triage keywords keybert
docker compose run --rm pipeline dome-triage keywords build-lexicon

# or run the whole chain at once:
docker compose run --rm pipeline dome-triage pipeline run \
  --steps ingest,dedupe,manifest,tfidf,keybert,build-lexicon

# human curation UI (http://localhost:8501)
docker compose up curate

# after a curation session, fold decisions back into the canonical dataset:
docker compose run --rm pipeline dome-triage curate materialize
```

Every command reads its four config files from `configs/` by default (override with
`--config-dir`).

Every step reads/writes plain CSV/Parquet files under `data/` (gitignored) via paths declared in
`configs/`, so any step can be run, inspected, and re-run independently — see `AGENTS.md` for the
full step list and the human-in-the-loop checkpoints.

## Status

**Implemented (this pass):** repo scaffold, Docker, data consolidation across the six sources
above into one canonical labeled dataset with full provenance and conflict-flagging, a Dockerized
Streamlit curation app, and a TF-IDF + KeyBERT keyword extraction step with a human review
checkpoint.

**Not yet built** (specified in `ROADMAP.md`): EDAM/domain ontology tagging, baseline and
BERT/LLM classifiers, probability calibration and confidence-based routing, the bulk historical
Europe PMC scan, and the daily production pipeline.

## License

CC BY 4.0 — see `LICENSE.md`. Matches the license used by `DOME_Top_Curate` and `dome-schema`.
