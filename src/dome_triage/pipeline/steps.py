"""Shared step functions. Every CLI subcommand in cli.py and `dome-triage pipeline run` call the
SAME functions defined here -- there is no separate workflow-engine orchestration, just the
STEP_FUNCS dict below called in sequence (see AGENTS.md)."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from dome_triage.config import PipelineConfig, resolve_path
from dome_triage.dedupe.consolidate import conflicts_dataframe, consolidate, to_dataframe
from dome_triage.fulltext.manifest import build_manifest
from dome_triage.ingest.enrich import enrich_missing_metadata
from dome_triage.ingest.epmc_client import EpmcClient
from dome_triage.ingest.source_loaders import (
    dataframe_to_raw_records,
    load_all_sources,
    raw_records_to_dataframe,
)
from dome_triage.keywords.keybert_extract import extract_keybert_terms
from dome_triage.keywords.lexicon import build_candidate_lexicon, load_seed_terms
from dome_triage.keywords.tfidf_extract import extract_tfidf_terms


def step_ingest_load_sources(cfg: PipelineConfig) -> None:
    cfg.ensure_dirs()
    records, unresolved = load_all_sources(cfg.sources)
    raw_records_to_dataframe(records).to_csv(cfg.path("raw_records"), index=False)
    if unresolved:
        pd.DataFrame(unresolved).to_csv(cfg.path("unresolved_needs_id_lookup"), index=False)
    print(
        f"Loaded {len(records)} raw records ({len(unresolved)} unresolved) from "
        f"{len(cfg.sources['label_sources'])} sources."
    )


def step_ingest_enrich_metadata(cfg: PipelineConfig) -> None:
    cfg.ensure_dirs()
    df = pd.read_csv(cfg.path("raw_records"), dtype=str)
    records = dataframe_to_raw_records(df)

    epmc_cfg = cfg.sources.get("epmc", {})
    client = EpmcClient(
        base_url=epmc_cfg.get("base_url", "https://www.ebi.ac.uk/europepmc/webservices/rest"),
        page_size=epmc_cfg.get("page_size", 100),
        max_retries=epmc_cfg.get("max_retries", 5),
        backoff_factor=epmc_cfg.get("backoff_factor", 1.5),
    )
    try:
        enriched = enrich_missing_metadata(records, client)
    finally:
        client.close()

    raw_records_to_dataframe(enriched).to_csv(cfg.path("raw_records_enriched"), index=False)
    print(f"Enriched metadata for {len(enriched)} records -> {cfg.path('raw_records_enriched')}")


def step_dedupe_consolidate(cfg: PipelineConfig) -> None:
    cfg.ensure_dirs()
    enriched_path = cfg.path("raw_records_enriched")
    source_path = enriched_path if enriched_path.exists() else cfg.path("raw_records")
    records = dataframe_to_raw_records(pd.read_csv(source_path, dtype=str))

    id_priority = tuple(cfg.sources.get("dedup", {}).get("id_priority", ["pmcid", "doi", "pmid"]))
    canonical_records = consolidate(records, id_priority)

    to_dataframe(canonical_records).to_csv(cfg.path("canonical_dataset"), index=False)
    conflicts_dataframe(canonical_records).to_csv(cfg.path("conflicts_for_review"), index=False)

    n_conflict = sum(1 for r in canonical_records if r.has_conflict)
    print(
        f"Consolidated {len(records)} raw records into {len(canonical_records)} canonical "
        f"records ({n_conflict} conflicts) -> {cfg.path('canonical_dataset')}"
    )


def step_fulltext_build_manifest(cfg: PipelineConfig) -> None:
    cfg.ensure_dirs()
    manifest = build_manifest(cfg.sources)
    manifest.to_csv(cfg.path("fulltext_manifest"), index=False)

    canonical_path = cfg.path("canonical_dataset")
    if canonical_path.exists() and not manifest.empty:
        dataset = pd.read_csv(canonical_path, dtype=str)
        available_pmcids = set(manifest["pmcid"].dropna())
        is_available = dataset["pmcid"].isin(available_pmcids)
        dataset["fulltext_available"] = is_available
        dataset["fulltext_manifest_ref"] = dataset["pmcid"].where(is_available)
        dataset.to_csv(canonical_path, index=False)

    print(f"Built full-text manifest with {len(manifest)} entries -> {cfg.path('fulltext_manifest')}")


def _load_labeled_texts(cfg: PipelineConfig, label: str) -> list[str]:
    dataset = pd.read_csv(cfg.path("canonical_dataset"), dtype=str)
    subset = dataset[dataset["label"] == label]
    texts = (subset["title"].fillna("") + ". " + subset["abstract"].fillna("")).tolist()
    return [t for t in texts if t.strip(". ")]


def step_keywords_tfidf(cfg: PipelineConfig) -> None:
    cfg.ensure_dirs()
    corpora_cfg = cfg.tfidf.get("corpora", {})
    positive_texts = _load_labeled_texts(cfg, corpora_cfg.get("positive_label", "positive"))
    baseline_texts = _load_labeled_texts(cfg, corpora_cfg.get("baseline_label", "negative"))

    terms_df = extract_tfidf_terms(positive_texts, baseline_texts, cfg.tfidf)
    output_path = cfg.path("interim_dir") / "tfidf_terms.csv"
    terms_df.to_csv(output_path, index=False)
    print(
        f"Extracted {len(terms_df)} TF-IDF terms from {len(positive_texts)} positive / "
        f"{len(baseline_texts)} baseline documents -> {output_path}"
    )


def step_keywords_keybert(cfg: PipelineConfig) -> None:
    cfg.ensure_dirs()
    positive_label = cfg.tfidf.get("corpora", {}).get("positive_label", "positive")
    positive_texts = _load_labeled_texts(cfg, positive_label)

    terms_df = extract_keybert_terms(positive_texts, cfg.keybert)
    output_path = cfg.path("interim_dir") / "keybert_terms.csv"
    terms_df.to_csv(output_path, index=False)
    print(
        f"Extracted {len(terms_df)} KeyBERT terms from {len(positive_texts)} positive "
        f"documents -> {output_path}"
    )


def step_keywords_build_lexicon(cfg: PipelineConfig) -> None:
    cfg.ensure_dirs()
    tfidf_df = pd.read_csv(cfg.path("interim_dir") / "tfidf_terms.csv")
    keybert_df = pd.read_csv(cfg.path("interim_dir") / "keybert_terms.csv")

    seed_path = Path(cfg.pipeline["keywords"]["seed_terms"])
    seed_df = load_seed_terms(seed_path) if seed_path.exists() else None

    candidates = build_candidate_lexicon(tfidf_df, keybert_df, seed_df)
    output_path = resolve_path(cfg.pipeline["keywords"]["candidates"])
    output_path.parent.mkdir(parents=True, exist_ok=True)
    candidates.to_csv(output_path, index=False)
    print(
        f"Built candidate lexicon with {len(candidates)} terms -> {output_path}. "
        "Review via the Streamlit 'Keyword Review' page."
    )


STEP_FUNCS = {
    "ingest": step_ingest_load_sources,
    "enrich": step_ingest_enrich_metadata,
    "dedupe": step_dedupe_consolidate,
    "manifest": step_fulltext_build_manifest,
    "tfidf": step_keywords_tfidf,
    "keybert": step_keywords_keybert,
    "build-lexicon": step_keywords_build_lexicon,
}


def run_steps(cfg: PipelineConfig, steps: list[str]) -> None:
    for step in steps:
        if step not in STEP_FUNCS:
            raise ValueError(f"Unknown step '{step}'. Valid steps: {list(STEP_FUNCS)}")
        STEP_FUNCS[step](cfg)
