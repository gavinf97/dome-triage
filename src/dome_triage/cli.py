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
keywords_app = typer.Typer(help="TF-IDF + KeyBERT keyword extraction and lexicon building.")
curate_app = typer.Typer(help="Human curation app and event-log materialization.")
pipeline_app = typer.Typer(help="Run multiple steps in sequence.")

app.add_typer(ingest_app, name="ingest")
app.add_typer(dedupe_app, name="dedupe")
app.add_typer(fulltext_app, name="fulltext")
app.add_typer(keywords_app, name="keywords")
app.add_typer(curate_app, name="curate")
app.add_typer(pipeline_app, name="pipeline")

_CONFIG_DIR_OPTION = typer.Option("configs", "--config-dir", help="Directory containing the 4 config YAMLs.")


def _load_config(config_dir: str) -> PipelineConfig:
    base = resolve_path(config_dir)
    return PipelineConfig(
        sources_path=base / "sources.yaml",
        pipeline_path=base / "pipeline.yaml",
        tfidf_path=base / "tfidf.yaml",
        keybert_path=base / "keybert.yaml",
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
        ..., "--steps", help="Comma-separated step names, e.g. ingest,dedupe,manifest,tfidf,keybert,build-lexicon"
    ),
    config_dir: str = _CONFIG_DIR_OPTION,
) -> None:
    cfg = _load_config(config_dir)
    step_list = [s.strip() for s in steps.split(",") if s.strip()]
    pipeline_steps.run_steps(cfg, step_list)


if __name__ == "__main__":
    app()
