"""Typer CLI. Every subcommand is a thin wrapper around the shared functions in
pipeline/steps.py (or, for `curate` / `fulltext fetch`, curate/state.py and fulltext/manifest.py
directly) -- there is no separate workflow-engine orchestration, see AGENTS.md.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import typer

from dome_triage.config import PipelineConfig, resolve_path
from dome_triage.curate.state import materialize_events
from dome_triage.fulltext.manifest import save_fulltext_xml
from dome_triage.pipeline import steps as pipeline_steps

app = typer.Typer(help="dome-triage: literature triage pipeline for the DOME registry.")

ingest_app = typer.Typer(help="Load and enrich records from the configured label sources.")
dedupe_app = typer.Typer(help="Cluster and consolidate raw records into the canonical dataset.")
fulltext_app = typer.Typer(help="Build/query the full-text availability manifest.")
keywords_app = typer.Typer(help="TF-IDF + KeyBERT keyword extraction, lexicon, and scoring.")
bulk_match_app = typer.Typer(help="Bulk blunt-match candidate construction against Europe PMC.")
sampling_app = typer.Typer(help="Stratified sampling over the scored bulk candidate pool.")
curate_app = typer.Typer(help="Human curation app and event-log materialization.")
pipeline_app = typer.Typer(help="Run multiple steps in sequence.")

app.add_typer(ingest_app, name="ingest")
app.add_typer(dedupe_app, name="dedupe")
app.add_typer(fulltext_app, name="fulltext")
app.add_typer(keywords_app, name="keywords")
app.add_typer(bulk_match_app, name="bulk-match")
app.add_typer(sampling_app, name="sampling")
app.add_typer(curate_app, name="curate")
app.add_typer(pipeline_app, name="pipeline")

_CONFIG_DIR_OPTION = typer.Option("configs", "--config-dir", help="Directory containing the config YAMLs.")


def _load_config(config_dir: str) -> PipelineConfig:
    base = resolve_path(config_dir)
    return PipelineConfig(
        sources_path=base / "sources.yaml",
        pipeline_path=base / "pipeline.yaml",
        tfidf_path=base / "tfidf.yaml",
        keybert_path=base / "keybert.yaml",
        sampling_path=base / "sampling.yaml",
    )


@ingest_app.command("load-sources")
def ingest_load_sources(config_dir: str = _CONFIG_DIR_OPTION) -> None:
    pipeline_steps.step_ingest_load_sources(_load_config(config_dir))


@ingest_app.command("enrich-metadata")
def ingest_enrich_metadata(config_dir: str = _CONFIG_DIR_OPTION) -> None:
    pipeline_steps.step_ingest_enrich_metadata(_load_config(config_dir))


@dedupe_app.command("consolidate")
def dedupe_consolidate(config_dir: str = _CONFIG_DIR_OPTION) -> None:
    pipeline_steps.step_dedupe_consolidate(_load_config(config_dir))


@fulltext_app.command("build-manifest")
def fulltext_build_manifest(config_dir: str = _CONFIG_DIR_OPTION) -> None:
    pipeline_steps.step_fulltext_build_manifest(_load_config(config_dir))


@fulltext_app.command("fetch")
def fulltext_fetch(
    pmcid: str = typer.Option(..., "--pmcid", help="PMCID to fetch full-text XML for."),
    config_dir: str = _CONFIG_DIR_OPTION,
) -> None:
    cfg = _load_config(config_dir)
    output_dir = resolve_path(cfg.pipeline["fulltext"]["local_dir"])
    saved_path = save_fulltext_xml(pmcid, output_dir)
    if saved_path is None:
        typer.echo(f"Could not fetch full-text XML for {pmcid} (not open-access or not found).")
        raise typer.Exit(code=1)
    typer.echo(f"Saved {saved_path}")


@keywords_app.command("tfidf")
def keywords_tfidf(config_dir: str = _CONFIG_DIR_OPTION) -> None:
    pipeline_steps.step_keywords_tfidf(_load_config(config_dir))


@keywords_app.command("keybert")
def keywords_keybert(config_dir: str = _CONFIG_DIR_OPTION) -> None:
    pipeline_steps.step_keywords_keybert(_load_config(config_dir))


@keywords_app.command("build-lexicon")
def keywords_build_lexicon(config_dir: str = _CONFIG_DIR_OPTION) -> None:
    pipeline_steps.step_keywords_build_lexicon(_load_config(config_dir))


@keywords_app.command("lexicon-stats")
def keywords_lexicon_stats(config_dir: str = _CONFIG_DIR_OPTION) -> None:
    """Term-counts remaining at a range of thresholds -- pick a defensible cutoff from real
    numbers instead of reviewing all ~40k candidates by hand."""
    pipeline_steps.step_keywords_lexicon_stats(_load_config(config_dir))


@keywords_app.command("materialize-lexicon")
def keywords_materialize_lexicon(config_dir: str = _CONFIG_DIR_OPTION) -> None:
    """Folds keyword_review_events.csv (from the Streamlit Keyword Review page) into
    keyword_lexicon.csv (positive), keyword_lexicon_exclusionary.csv (negative), and
    keyword_lexicon_irrelevant.csv (irrelevant) -- last decision per term wins, regardless of
    which pile or manual entry produced it."""
    pipeline_steps.step_keywords_materialize_lexicon(_load_config(config_dir))


@keywords_app.command("seed-additional-terms")
def keywords_seed_additional_terms(config_dir: str = _CONFIG_DIR_OPTION) -> None:
    """Writes keywords/curated_terms.py's curated positive/negative additions (ML algorithms,
    generative/agentic/LLM terms, flagship biodata terms, non-methods publication-type terms) to
    their own tier-2 files -- separate from your human-curated tier-1 lexicon/exclusionary_lexicon,
    skipping anything already decided."""
    pipeline_steps.step_keywords_seed_additional_terms(_load_config(config_dir))


@keywords_app.command("suggest-final-lexicon")
def keywords_suggest_final_lexicon(config_dir: str = _CONFIG_DIR_OPTION) -> None:
    """Combines tier 1 (materialized lexicon/exclusionary_lexicon) with tier 2 (added terms),
    runs the explainable cleanup heuristic (redundant-unigram removal, cross-list tension
    flagging), and writes tier 3 -- suggested_lexicon / suggested_exclusionary_lexicon / a
    cleanup log. Never modifies tier 1's live files; promoting tier 3 to production is manual."""
    pipeline_steps.step_keywords_suggest_final_lexicon(_load_config(config_dir))


_EXCLUSIONARY_WEIGHT_OPTION = typer.Option(
    1.0,
    "--exclusionary-weight",
    help="Penalty weight applied to the exclusionary lexicon's score, if "
    "data/processed/keyword_lexicon_exclusionary.csv exists (from `keywords materialize-lexicon`).",
)


@keywords_app.command("scoring-bakeoff")
def keywords_scoring_bakeoff(
    exclusionary_weight: float = _EXCLUSIONARY_WEIGHT_OPTION,
    config_dir: str = _CONFIG_DIR_OPTION,
) -> None:
    """Validates every relevance-scoring algorithm against the already-known-labeled records
    before trusting any of them to rank the unlabeled bulk pool."""
    pipeline_steps.step_keywords_scoring_bakeoff(_load_config(config_dir), exclusionary_weight)


@keywords_app.command("score-bulk-match")
def keywords_score_bulk_match(
    scorer: str = typer.Option(
        "weighted-sum", "--scorer", help='One of "weighted-sum", "bm25", "tfidf-cosine", or "all".'
    ),
    exclusionary_weight: float = _EXCLUSIONARY_WEIGHT_OPTION,
    config_dir: str = _CONFIG_DIR_OPTION,
) -> None:
    pipeline_steps.step_keywords_score_bulk_match(_load_config(config_dir), scorer, exclusionary_weight)


@bulk_match_app.command("fetch")
def bulk_match_fetch(
    year_from: int = typer.Option(..., "--year-from", help="First year to fetch (inclusive)."),
    year_to: int = typer.Option(..., "--year-to", help="Last year to fetch (inclusive)."),
    config_dir: str = _CONFIG_DIR_OPTION,
) -> None:
    """Fetches every AI/ML-matching Europe PMC record (resultType=core, full metadata incl. MeSH)
    for the whole [year_from, year_to] range in one invocation -- one EPMC query per year
    internally (checkpointed, resumable), with live per-year progress and a printed + logged
    AI-only/ML-only/combined-deduplicated count breakdown."""
    pipeline_steps.step_bulk_match_fetch(_load_config(config_dir), year_from, year_to)


@bulk_match_app.command("build-candidates")
def bulk_match_build_candidates(config_dir: str = _CONFIG_DIR_OPTION) -> None:
    """Consolidates every completed year fetched so far into one deduplicated candidate pool."""
    pipeline_steps.step_bulk_match_build_candidates(_load_config(config_dir))


@sampling_app.command("stratify")
def sampling_stratify(config_dir: str = _CONFIG_DIR_OPTION) -> None:
    """Stratified sample (match-score band x journal x year, capped per stratum in
    configs/sampling.yaml) over the scored bulk pool -- merges new candidates into
    canonical_dataset.csv for the curation app's queue."""
    pipeline_steps.step_sampling_stratify(_load_config(config_dir))


@ingest_app.command("fetch-clear-negatives")
def ingest_fetch_clear_negatives(
    year_from: int = typer.Option(..., "--year-from"),
    year_to: int = typer.Option(..., "--year-to"),
    sample_size: int = typer.Option(2000, "--sample-size"),
    config_dir: str = _CONFIG_DIR_OPTION,
) -> None:
    """Samples genuine AI/ML-free negatives (random narrow date windows) -- merges into
    canonical_dataset.csv for the curation app's queue, same as sampling stratify."""
    pipeline_steps.step_ingest_fetch_clear_negatives(
        _load_config(config_dir), year_from, year_to, sample_size
    )


@curate_app.command("launch")
def curate_launch(
    port: int = typer.Option(8501, "--port"),
    config_dir: str = _CONFIG_DIR_OPTION,
) -> None:
    """Launches the Streamlit curation app (blocking). Prefer `docker compose up curate` for
    normal use; this command exists for local (non-Docker) development."""
    app_path = Path(__file__).resolve().parent / "curate" / "app.py"
    subprocess.run(
        [sys.executable, "-m", "streamlit", "run", str(app_path), "--server.port", str(port)],
        check=True,
    )


@curate_app.command("materialize")
def curate_materialize(config_dir: str = _CONFIG_DIR_OPTION) -> None:
    """Folds curation_events.csv into canonical_dataset.csv (last decision wins per record,
    conflicts with a trusted prior label are flagged, never silently overwritten)."""
    cfg = _load_config(config_dir)
    events_path = resolve_path(cfg.pipeline["curation"]["events_log"])
    dataset_path = cfg.path("canonical_dataset")
    materialize_events(dataset_path, events_path, dataset_path)
    typer.echo(f"Materialized {events_path} into {dataset_path}")


@pipeline_app.command("run")
def pipeline_run(
    steps: str = typer.Option(
        ...,
        "--steps",
        help=(
            "Comma-separated step names from: ingest, enrich, dedupe, manifest, tfidf, keybert, "
            "build-lexicon, lexicon-stats, scoring-bakeoff, bulk-match-build-candidates, "
            "sampling-stratify. A convenience for re-running an already-verified chain quickly -- "
            "the manual one-command-at-a-time flow (see README.md) is the primary workflow."
        ),
    ),
    config_dir: str = _CONFIG_DIR_OPTION,
) -> None:
    cfg = _load_config(config_dir)
    step_list = [s.strip() for s in steps.split(",") if s.strip()]
    pipeline_steps.run_steps(cfg, step_list)


if __name__ == "__main__":
    app()
