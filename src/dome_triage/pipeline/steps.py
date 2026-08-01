"""Shared step functions. Every CLI subcommand in cli.py and `dome-triage pipeline run` call the
SAME functions defined here -- there is no separate workflow-engine orchestration, just the
STEP_FUNCS dict below called in sequence (see AGENTS.md). Every step calls `finish_step(...)`
before returning -- no generated file without a provenance entry (AGENTS.md rule)."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from tqdm import tqdm

from dome_triage.config import PipelineConfig, resolve_path
from dome_triage.curate.state import backup_file
from dome_triage.curate.term_review_state import materialize_term_events
from dome_triage.dedupe.consolidate import conflicts_dataframe, consolidate, to_dataframe
from dome_triage.fulltext.manifest import build_manifest
from dome_triage.ingest.bulk_match import count_ai_ml_breakdown, fetch_ai_ml_range, load_bulk_match_year
from dome_triage.ingest.clear_negative_sampler import fetch_clear_negatives
from dome_triage.ingest.enrich import enrich_missing_metadata
from dome_triage.ingest.epmc_client import EpmcClient
from dome_triage.ingest.source_loaders import (
    dataframe_to_raw_records,
    load_all_sources,
    raw_records_to_dataframe,
)
from dome_triage.keywords.curated_terms import (
    ADDED_NEGATIVE_TERMS,
    ADDED_POSITIVE_TERMS,
    PROTECTED_UNIGRAMS,
)
from dome_triage.keywords.keybert_extract import extract_keybert_terms
from dome_triage.keywords.lexicon import build_candidate_lexicon, lexicon_stats, load_seed_terms
from dome_triage.keywords.lexicon_cleanup import clean_lexicon
from dome_triage.keywords.scoring import SCORERS, WeightedSumScorer, load_lexicon_terms_and_weights
from dome_triage.keywords.scoring_bakeoff import run_bakeoff
from dome_triage.keywords.tfidf_extract import extract_tfidf_terms
from dome_triage.provenance import finish_step
from dome_triage.sampling.stratified import build_strata, stratified_sample
from dome_triage.schema import RawRecord


def step_ingest_load_sources(cfg: PipelineConfig) -> None:
    started_at = time.monotonic()
    cfg.ensure_dirs()
    records, unresolved = load_all_sources(cfg.sources)
    raw_records_to_dataframe(records).to_csv(cfg.path("raw_records"), index=False)
    if unresolved:
        pd.DataFrame(unresolved).to_csv(cfg.path("unresolved_needs_id_lookup"), index=False)

    outputs = [cfg.path("raw_records")]
    if unresolved:
        outputs.append(cfg.path("unresolved_needs_id_lookup"))
    finish_step(
        "ingest.load-sources",
        inputs=[],
        outputs=outputs,
        params={"n_sources": len(cfg.sources["label_sources"])},
        notes=f"{len(records)} raw records, {len(unresolved)} unresolved",
        started_at=started_at,
    )


def step_ingest_enrich_metadata(cfg: PipelineConfig) -> None:
    started_at = time.monotonic()
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
    finish_step(
        "ingest.enrich-metadata",
        inputs=[cfg.path("raw_records")],
        outputs=[cfg.path("raw_records_enriched")],
        started_at=started_at,
    )


def step_dedupe_consolidate(cfg: PipelineConfig) -> None:
    started_at = time.monotonic()
    cfg.ensure_dirs()
    enriched_path = cfg.path("raw_records_enriched")
    source_path = enriched_path if enriched_path.exists() else cfg.path("raw_records")
    records = dataframe_to_raw_records(pd.read_csv(source_path, dtype=str))

    id_priority = tuple(cfg.sources.get("dedup", {}).get("id_priority", ["pmcid", "doi", "pmid"]))
    canonical_records = consolidate(records, id_priority)

    to_dataframe(canonical_records).to_csv(cfg.path("canonical_dataset"), index=False)
    conflicts_dataframe(canonical_records).to_csv(cfg.path("conflicts_for_review"), index=False)

    n_conflict = sum(1 for r in canonical_records if r.has_conflict)
    finish_step(
        "dedupe.consolidate",
        inputs=[source_path],
        outputs=[cfg.path("canonical_dataset"), cfg.path("conflicts_for_review")],
        params={"id_priority": list(id_priority)},
        notes=f"{len(records)} raw -> {len(canonical_records)} canonical ({n_conflict} conflicts)",
        started_at=started_at,
    )


def step_fulltext_build_manifest(cfg: PipelineConfig) -> None:
    started_at = time.monotonic()
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

    finish_step(
        "fulltext.build-manifest",
        inputs=[canonical_path] if canonical_path.exists() else [],
        outputs=[cfg.path("fulltext_manifest")] + ([canonical_path] if canonical_path.exists() else []),
        started_at=started_at,
    )


def _load_labeled_texts(cfg: PipelineConfig, label: str) -> list[str]:
    dataset = pd.read_csv(cfg.path("canonical_dataset"), dtype=str)
    subset = dataset[dataset["label"] == label]
    texts = (subset["title"].fillna("") + ". " + subset["abstract"].fillna("")).tolist()
    return [t for t in texts if t.strip(". ")]


def step_keywords_tfidf(cfg: PipelineConfig) -> None:
    started_at = time.monotonic()
    cfg.ensure_dirs()
    corpora_cfg = cfg.tfidf.get("corpora", {})
    positive_texts = _load_labeled_texts(cfg, corpora_cfg.get("positive_label", "positive"))
    baseline_texts = _load_labeled_texts(cfg, corpora_cfg.get("baseline_label", "negative"))

    terms_df = extract_tfidf_terms(positive_texts, baseline_texts, cfg.tfidf)
    output_path = cfg.path("interim_dir") / "tfidf_terms.csv"
    terms_df.to_csv(output_path, index=False)
    finish_step(
        "keywords.tfidf",
        inputs=[cfg.path("canonical_dataset")],
        outputs=[output_path],
        notes=f"{len(positive_texts)} positive / {len(baseline_texts)} baseline documents",
        started_at=started_at,
    )


def step_keywords_keybert(cfg: PipelineConfig) -> None:
    started_at = time.monotonic()
    cfg.ensure_dirs()
    positive_label = cfg.tfidf.get("corpora", {}).get("positive_label", "positive")
    positive_texts = _load_labeled_texts(cfg, positive_label)

    terms_df = extract_keybert_terms(positive_texts, cfg.keybert)
    output_path = cfg.path("interim_dir") / "keybert_terms.csv"
    terms_df.to_csv(output_path, index=False)
    finish_step(
        "keywords.keybert",
        inputs=[cfg.path("canonical_dataset")],
        outputs=[output_path],
        notes=f"{len(positive_texts)} positive documents",
        started_at=started_at,
    )


def step_keywords_build_lexicon(cfg: PipelineConfig) -> None:
    started_at = time.monotonic()
    cfg.ensure_dirs()
    tfidf_path = cfg.path("interim_dir") / "tfidf_terms.csv"
    keybert_path = cfg.path("interim_dir") / "keybert_terms.csv"
    tfidf_df = pd.read_csv(tfidf_path)
    keybert_df = pd.read_csv(keybert_path)

    seed_path = Path(cfg.pipeline["keywords"]["seed_terms"])
    seed_df = load_seed_terms(seed_path) if seed_path.exists() else None

    candidates = build_candidate_lexicon(tfidf_df, keybert_df, seed_df)
    output_path = resolve_path(cfg.pipeline["keywords"]["candidates"])
    output_path.parent.mkdir(parents=True, exist_ok=True)
    candidates.to_csv(output_path, index=False)
    finish_step(
        "keywords.build-lexicon",
        inputs=[tfidf_path, keybert_path] + ([seed_path] if seed_path.exists() else []),
        outputs=[output_path],
        notes=f"{len(candidates)} candidate terms -- review via `keywords lexicon-stats` "
        "then the Streamlit Keyword Review page",
        started_at=started_at,
    )


def step_keywords_materialize_lexicon(cfg: PipelineConfig) -> None:
    """Folds keyword_review_events.csv (from the Streamlit Keyword Review page) into
    keyword_lexicon.csv (positive), keyword_lexicon_exclusionary.csv (negative), and
    keyword_lexicon_irrelevant.csv (irrelevant) -- last decision per term wins, regardless of
    which pile or manual entry produced it. Unlike `curate materialize`, this calls finish_step:
    keyword_lexicon.csv is a first-class pipeline artifact consumed by
    scoring-bakeoff/score-bulk-match, not a dataset that already has provenance from earlier
    ingest/dedupe steps."""
    started_at = time.monotonic()
    candidates_path = resolve_path(cfg.pipeline["keywords"]["candidates"])
    events_path = resolve_path(cfg.pipeline["keyword_review"]["events_log"])
    lexicon_path = resolve_path(cfg.pipeline["keywords"]["lexicon"])
    exclusionary_path = resolve_path(cfg.pipeline["keywords"]["exclusionary_lexicon"])
    irrelevant_path = resolve_path(cfg.pipeline["keyword_review"]["irrelevant_terms"])

    counts = materialize_term_events(
        candidates_path, events_path, lexicon_path, exclusionary_path, irrelevant_path
    )

    finish_step(
        "keywords.materialize-lexicon",
        inputs=[candidates_path, events_path],
        outputs=[lexicon_path, exclusionary_path, irrelevant_path, candidates_path],
        notes=f"{counts['positive']} positive / {counts['negative']} negative / "
        f"{counts['irrelevant']} irrelevant",
        started_at=started_at,
    )


def _lookup_candidate_stats(candidates_df: pd.DataFrame, term: str):
    match = candidates_df[candidates_df["term"].str.lower() == term.lower()]
    if match.empty:
        return None, None
    row = match.iloc[0]
    return row.get("discriminative_score"), row.get("document_frequency")


def _already_present_terms(*paths: Path) -> set[str]:
    terms: set[str] = set()
    for path in paths:
        if path.exists():
            df = pd.read_csv(path, dtype=str)
            if "term" in df.columns:
                terms |= set(df["term"].dropna().str.lower())
    return terms


_ADDED_TERM_COLUMNS = ["term", "discriminative_score", "document_frequency", "source", "notes"]


def step_keywords_seed_additional_terms(cfg: PipelineConfig) -> None:
    """Writes keywords/curated_terms.py's positive/negative additions to their own tier-2 files
    (added_positive_terms / added_negative_terms) -- skipping anything already decided in
    keyword_review_events.csv or already present in the materialized tier-1 lexicon/exclusionary
    files, and pulling real discriminative_score/document_frequency from
    keyword_lexicon_candidates.csv where the term was actually extracted (blank otherwise). Never
    touches the tier-1 files -- see keywords.suggest-final-lexicon for how tier 2 gets combined
    with tier 1."""
    started_at = time.monotonic()
    candidates_path = resolve_path(cfg.pipeline["keywords"]["candidates"])
    candidates_df = pd.read_csv(candidates_path)

    events_path = resolve_path(cfg.pipeline["keyword_review"]["events_log"])
    lexicon_path = resolve_path(cfg.pipeline["keywords"]["lexicon"])
    exclusionary_path = resolve_path(cfg.pipeline["keywords"]["exclusionary_lexicon"])
    already_decided = _already_present_terms(events_path, lexicon_path, exclusionary_path)

    def _build_rows(term_specs: list[dict]) -> list[dict]:
        rows = []
        for spec in term_specs:
            term = spec["term"]
            if term.lower() in already_decided:
                continue
            discriminative_score, document_frequency = _lookup_candidate_stats(candidates_df, term)
            rows.append(
                {
                    "term": term,
                    "discriminative_score": discriminative_score,
                    "document_frequency": document_frequency,
                    "source": f"claude_seed_{spec['category']}",
                    "notes": spec["category"],
                }
            )
        return rows

    positive_rows = _build_rows(ADDED_POSITIVE_TERMS)
    negative_rows = _build_rows(ADDED_NEGATIVE_TERMS)

    added_positive_path = resolve_path(cfg.pipeline["keywords"]["added_positive_terms"])
    added_negative_path = resolve_path(cfg.pipeline["keywords"]["added_negative_terms"])
    added_positive_path.parent.mkdir(parents=True, exist_ok=True)
    backup_file(added_positive_path)
    backup_file(added_negative_path)

    pd.DataFrame(positive_rows, columns=_ADDED_TERM_COLUMNS).to_csv(added_positive_path, index=False)
    pd.DataFrame(negative_rows, columns=_ADDED_TERM_COLUMNS).to_csv(added_negative_path, index=False)

    finish_step(
        "keywords.seed-additional-terms",
        inputs=[candidates_path]
        + ([events_path] if events_path.exists() else [])
        + ([lexicon_path] if lexicon_path.exists() else [])
        + ([exclusionary_path] if exclusionary_path.exists() else []),
        outputs=[added_positive_path, added_negative_path],
        notes=f"{len(positive_rows)}/{len(ADDED_POSITIVE_TERMS)} positive, "
        f"{len(negative_rows)}/{len(ADDED_NEGATIVE_TERMS)} negative added "
        "(rest skipped -- already decided)",
        started_at=started_at,
    )


def step_keywords_suggest_final_lexicon(cfg: PipelineConfig) -> None:
    """Combines tier 1 (materialized keyword_lexicon.csv / keyword_lexicon_exclusionary.csv) with
    tier 2 (keyword_lexicon_added_positive.csv / _added_negative.csv), runs the cleanup heuristic
    (keywords/lexicon_cleanup.py::clean_lexicon), and writes tier 3: suggested_lexicon,
    suggested_exclusionary_lexicon, suggested_cleanup_log. Never modifies tier 1's live files --
    promoting tier 3 to production is a separate, manual decision."""
    started_at = time.monotonic()
    lexicon_path = resolve_path(cfg.pipeline["keywords"]["lexicon"])
    exclusionary_path = resolve_path(cfg.pipeline["keywords"]["exclusionary_lexicon"])
    added_positive_path = resolve_path(cfg.pipeline["keywords"]["added_positive_terms"])
    added_negative_path = resolve_path(cfg.pipeline["keywords"]["added_negative_terms"])

    if not lexicon_path.exists():
        raise FileNotFoundError(f"{lexicon_path} not found -- run `keywords materialize-lexicon` first.")
    if not added_positive_path.exists():
        raise FileNotFoundError(f"{added_positive_path} not found -- run `keywords seed-additional-terms` first.")

    positive_df = pd.concat(
        [pd.read_csv(lexicon_path), pd.read_csv(added_positive_path)], ignore_index=True
    )
    negative_frames = [pd.read_csv(exclusionary_path)] if exclusionary_path.exists() else []
    if added_negative_path.exists():
        negative_frames.append(pd.read_csv(added_negative_path))
    negative_df = (
        pd.concat(negative_frames, ignore_index=True) if negative_frames else pd.DataFrame(columns=_ADDED_TERM_COLUMNS)
    )

    cleaned_positive, cleaned_negative, log_df = clean_lexicon(
        positive_df, negative_df, protected_unigrams=PROTECTED_UNIGRAMS
    )

    suggested_lexicon_path = resolve_path(cfg.pipeline["keywords"]["suggested_lexicon"])
    suggested_exclusionary_path = resolve_path(cfg.pipeline["keywords"]["suggested_exclusionary_lexicon"])
    suggested_log_path = resolve_path(cfg.pipeline["keywords"]["suggested_cleanup_log"])
    suggested_lexicon_path.parent.mkdir(parents=True, exist_ok=True)
    backup_file(suggested_lexicon_path)
    backup_file(suggested_exclusionary_path)
    backup_file(suggested_log_path)

    cleaned_positive.to_csv(suggested_lexicon_path, index=False)
    cleaned_negative.to_csv(suggested_exclusionary_path, index=False)
    log_df.to_csv(suggested_log_path, index=False)

    n_removed = int((log_df["action"] == "removed").sum()) if not log_df.empty else 0
    n_flagged = int((log_df["action"] == "kept_flagged").sum()) if not log_df.empty else 0

    finish_step(
        "keywords.suggest-final-lexicon",
        inputs=[lexicon_path, added_positive_path]
        + ([exclusionary_path] if exclusionary_path.exists() else [])
        + ([added_negative_path] if added_negative_path.exists() else []),
        outputs=[suggested_lexicon_path, suggested_exclusionary_path, suggested_log_path],
        notes=f"{len(cleaned_positive)} positive / {len(cleaned_negative)} negative terms "
        f"suggested; {n_removed} removed, {n_flagged} flagged (tension) -- see cleanup log",
        started_at=started_at,
    )


def step_keywords_lexicon_stats(cfg: PipelineConfig) -> None:
    """Prints (and saves) term-counts remaining at a range of thresholds -- the data-driven
    cutoff decision support tool, since reviewing all ~40k raw candidates by hand isn't
    practical."""
    started_at = time.monotonic()
    candidates_path = resolve_path(cfg.pipeline["keywords"]["candidates"])
    candidates = pd.read_csv(candidates_path)
    stats = lexicon_stats(candidates)

    output_path = cfg.path("processed_dir") / "lexicon_stats_report.csv"
    stats.to_csv(output_path, index=False)
    print(stats.to_string(index=False))

    finish_step(
        "keywords.lexicon-stats",
        inputs=[candidates_path],
        outputs=[output_path],
        started_at=started_at,
    )


def step_keywords_scoring_bakeoff(cfg: PipelineConfig, exclusionary_weight: float = 1.0) -> None:
    """Validates every MatchScorer against the already-known-labeled records in
    canonical_dataset.csv, TWICE per scorer: once using only the approved positive lexicon
    (condition "positive_lexicon_only"), and -- if keyword_lexicon_exclusionary.csv exists --
    again with the exclusionary lexicon's penalty applied too (condition
    "positive_plus_exclusionary_lexicon"). Two conditions side by side is a genuine before/after
    comparison of whether the exclusionary lexicon actually improves ranking quality, not just an
    assumption that it does."""
    started_at = time.monotonic()
    lexicon_path = cfg.path("processed_dir") / "keyword_lexicon.csv"
    if not lexicon_path.exists():
        raise FileNotFoundError(
            f"{lexicon_path} not found -- approve terms via the Streamlit Keyword Review page first."
        )
    lexicon_df = pd.read_csv(lexicon_path)
    lexicon_terms, term_weights = load_lexicon_terms_and_weights(lexicon_df)

    exclusionary_path = resolve_path(cfg.pipeline["keywords"]["exclusionary_lexicon"])
    exclusionary_terms: list[str] = []
    exclusionary_term_weights: dict[str, float] = {}
    if exclusionary_path.exists():
        exclusionary_df = pd.read_csv(exclusionary_path)
        exclusionary_terms, exclusionary_term_weights = load_lexicon_terms_and_weights(exclusionary_df)

    dataset = pd.read_csv(cfg.path("canonical_dataset"), dtype=str)
    labeled = dataset[dataset["label"].isin(["positive", "negative"])].copy()
    texts = (labeled["title"].fillna("") + ". " + labeled["abstract"].fillna("")).tolist()
    true_labels = (labeled["label"] == "positive").astype(int).tolist()
    n_positive = sum(true_labels)
    n_negative = len(true_labels) - n_positive

    def _build_scorers() -> dict:
        return {
            "weighted-sum": WeightedSumScorer(term_weights, exclusionary_term_weights),
            **{name: cls() for name, cls in SCORERS.items() if name != "weighted-sum"},
        }

    reports = [
        run_bakeoff(
            _build_scorers(), texts, true_labels, lexicon_terms, condition_label="positive_lexicon_only"
        )
    ]
    if exclusionary_terms:
        reports.append(
            run_bakeoff(
                _build_scorers(),
                texts,
                true_labels,
                lexicon_terms,
                exclusionary_terms=exclusionary_terms,
                exclusionary_weight=exclusionary_weight,
                condition_label="positive_plus_exclusionary_lexicon",
            )
        )
    report = pd.concat(reports, ignore_index=True).sort_values(["scorer", "condition"]).reset_index(drop=True)

    output_path = cfg.path("processed_dir") / "scoring_bakeoff_report.csv"
    report.to_csv(output_path, index=False)
    print(report.to_string(index=False))

    finish_step(
        "keywords.scoring-bakeoff",
        inputs=[lexicon_path, cfg.path("canonical_dataset")] + ([exclusionary_path] if exclusionary_terms else []),
        outputs=[output_path],
        params={
            "exclusionary_weight": exclusionary_weight,
            "n_exclusionary_terms": len(exclusionary_terms),
            "conditions_run": sorted(report["condition"].unique().tolist()),
        },
        notes=f"validated against {len(labeled)} already-labeled records "
        f"({n_positive} positive / {n_negative} negative) -- "
        + (
            "2 conditions (with/without exclusionary lexicon)"
            if exclusionary_terms
            else "1 condition (no keyword_lexicon_exclusionary.csv found)"
        ),
        started_at=started_at,
    )


def step_bulk_match_fetch(cfg: PipelineConfig, year_from: int, year_to: int) -> None:
    """Fetches every year in [year_from, year_to] of AI/ML-matching Europe PMC records in one
    invocation -- one EPMC query per year internally (checkpointed/resumable via existing .done
    markers), live per-year progress printed for a human watching a long multi-year run. Also
    computes and appends the AI-only/ML-only/combined-deduplicated hit-count breakdown for the
    requested range to bulk_match_summary.csv (three cheap count-only queries, no extra fetch)."""
    started_at = time.monotonic()
    checkpoint_dir = cfg.path("interim_dir") / "bulk_match_cache"
    epmc_cfg = cfg.sources.get("epmc", {})
    client = EpmcClient(
        base_url=epmc_cfg.get("base_url", "https://www.ebi.ac.uk/europepmc/webservices/rest"),
        page_size=epmc_cfg.get("page_size", 100),
        max_retries=epmc_cfg.get("max_retries", 5),
        backoff_factor=epmc_cfg.get("backoff_factor", 1.5),
    )
    try:
        output_paths = fetch_ai_ml_range(client, year_from, year_to, checkpoint_dir)
        breakdown = count_ai_ml_breakdown(client, year_from, year_to)
    finally:
        client.close()

    print(
        f"AI-mentioning: {breakdown['ai_count']} | ML-mentioning: {breakdown['ml_count']} | "
        f"Combined (deduplicated): {breakdown['combined_count']}"
    )

    summary_path = cfg.path("processed_dir") / "bulk_match_summary.csv"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_row = {
        "run_date_utc": datetime.now(timezone.utc).isoformat(),
        "year_from": year_from,
        "year_to": year_to,
        **breakdown,
    }
    header_needed = not summary_path.exists()
    pd.DataFrame([summary_row]).to_csv(summary_path, mode="a", header=header_needed, index=False)

    finish_step(
        "bulk-match.fetch",
        inputs=[],
        outputs=output_paths + [summary_path],
        params={"year_from": year_from, "year_to": year_to, **breakdown},
        notes=f"{len(output_paths)} year(s) fetched ({year_from}-{year_to})",
        started_at=started_at,
    )


def step_bulk_match_build_candidates(cfg: PipelineConfig) -> None:
    """Consolidates every *completed* per-year JSONL cache (still one file per year on disk even
    when `bulk-match fetch --year-from --year-to` fetched a whole range in a single invocation --
    that's an internal checkpointing detail, not something the human triggers) into one
    deduplicated candidate pool, keyed on **pmid**, not pmcid: PMCID is only assigned to records
    with full text deposited in PMC, while PMID exists for essentially every Europe PMC/MEDLINE
    entry -- deduping on pmcid would leave true duplicates in for any record without one (likely
    the majority of the bulk-matched pool, most of which won't be open-access full text). Rerun
    anytime after fetching more years to pick up newly completed ones.

    Processes one year's JSONL at a time -- converting each year straight to a DataFrame and
    discarding its RawRecord/Pydantic objects before loading the next year, deduplicating the
    running frame incrementally -- rather than materializing every year's Pydantic objects
    simultaneously. Confirmed necessary, not just theoretical: an earlier all-at-once version got
    OOM-killed (exit 137) on the real 2000-2026 fetch (~828k records, 5.3GB of JSONL) on a 15GB
    host; Pydantic model instances carry substantially more memory overhead per record than a
    DataFrame row."""
    started_at = time.monotonic()
    checkpoint_dir = cfg.path("interim_dir") / "bulk_match_cache"
    completed_years = []
    done_markers = sorted(checkpoint_dir.glob("bulk_match_*.done"))
    combined_df: pd.DataFrame | None = None
    for done_marker in tqdm(done_markers, desc="Loading + deduplicating per-year caches", unit="year"):
        year = int(done_marker.stem.split("_")[-1])
        jsonl_path = checkpoint_dir / f"bulk_match_{year}.jsonl"
        year_df = raw_records_to_dataframe(load_bulk_match_year(jsonl_path, year))
        running_total = len(year_df) if combined_df is None else len(combined_df) + len(year_df)
        print(f"  {year}: {len(year_df)} records (running total before dedup: {running_total})")
        combined_df = year_df if combined_df is None else pd.concat([combined_df, year_df], ignore_index=True)
        combined_df = combined_df.sort_values("pmid").drop_duplicates(subset=["pmid"], keep="first")
        completed_years.append(year)

    df = combined_df if combined_df is not None else raw_records_to_dataframe([])
    print(f"Deduplicated total: {len(df)} unique records (by pmid)")

    output_path = cfg.sampling_path("bulk_candidates")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_path, index=False)

    finish_step(
        "bulk-match.build-candidates",
        inputs=[checkpoint_dir / f"bulk_match_{y}.jsonl" for y in completed_years],
        outputs=[output_path],
        params={"years": completed_years},
        notes=f"{len(df)} deduplicated candidates from {len(completed_years)} completed year(s)",
        started_at=started_at,
    )


def _build_scorer(scorer_name: str, term_weights: dict[str, float], exclusionary_term_weights: dict[str, float]):
    if scorer_name == "weighted-sum":
        return WeightedSumScorer(term_weights, exclusionary_term_weights)
    return SCORERS[scorer_name]()


def _lookup_youden_threshold(bakeoff_report_path: Path, scorer_name: str, condition: str) -> float | None:
    """Reuses the threshold Step 11's bake-off already validated for this exact scorer+condition,
    rather than recomputing one -- keeps Step 12's positive/negative classification consistent
    with what was empirically checked, not a fresh guess. Returns None (no classification column
    added for this scorer) if the report doesn't exist yet or has no matching row -- run
    `keywords scoring-bakeoff` first to get one."""
    if not bakeoff_report_path.exists():
        return None
    report = pd.read_csv(bakeoff_report_path)
    match = report[(report["scorer"] == scorer_name) & (report["condition"] == condition)]
    if match.empty or pd.isna(match.iloc[0]["threshold_youden"]):
        return None
    return float(match.iloc[0]["threshold_youden"])


def _build_existing_label_lookup(canonical_df: pd.DataFrame) -> dict[str, tuple[str, str]]:
    """Maps every pmcid/pmid/doi in the canonical dataset to that record's (label,
    label_confidence). Small (~4k rows), so a plain loop is fine here -- contrast
    `_annotate_already_curated` below, which is vectorized because it runs against the
    700k+-row bulk candidate pool."""
    lookup: dict[str, tuple[str, str]] = {}
    for id_field in ("pmcid", "pmid", "doi"):
        subset = canonical_df[canonical_df[id_field].notna() & (canonical_df[id_field] != "")]
        for value, label, confidence in zip(subset[id_field], subset["label"], subset["label_confidence"]):
            lookup.setdefault(value, (label, confidence))
    return lookup


def _annotate_already_curated(candidates: pd.DataFrame, lookup: dict[str, tuple[str, str]]) -> pd.DataFrame:
    """Adds `already_curated`/`existing_label`/`existing_label_confidence` -- whether this bulk
    candidate already exists in canonical_dataset.csv from a prior curation round (by pmcid, else
    pmid, else doi), and if so what it was already decided as. Lets a human reviewing the
    stratified sample later (or `curate/state.py::CurationSession`'s `include_already_labeled`
    toggle) see and choose to skip or deliberately redo already-curated overlaps, rather than
    silently either re-reviewing or hiding them. Vectorized (three dict `.map()` calls, not a
    per-row Python loop) -- this runs against the full 700k+-row bulk pool."""
    label_lookup = {k: v[0] for k, v in lookup.items()}
    confidence_lookup = {k: v[1] for k, v in lookup.items()}

    existing_label = (
        candidates["pmcid"].map(label_lookup).fillna(candidates["pmid"].map(label_lookup)).fillna(
            candidates["doi"].map(label_lookup)
        )
    )
    existing_confidence = (
        candidates["pmcid"].map(confidence_lookup).fillna(candidates["pmid"].map(confidence_lookup)).fillna(
            candidates["doi"].map(confidence_lookup)
        )
    )

    candidates["already_curated"] = existing_label.notna()
    candidates["existing_label"] = existing_label.fillna("")
    candidates["existing_label_confidence"] = existing_confidence.fillna("")
    return candidates


def step_keywords_score_bulk_match(
    cfg: PipelineConfig, scorer_name: str, exclusionary_weight: float = 1.0
) -> None:
    """`scorer_name` is one of SCORERS' keys, or "all" to keep every scorer as a separate
    match_score__<name> column for later comparison. If keyword_lexicon_exclusionary.csv exists
    (from `keywords materialize-lexicon`), its terms are subtracted as a penalty, weighted by
    `exclusionary_weight`.

    Also adds, once regardless of how many scorers run: `has_pmcid` (full text available in PMC
    or not) and `already_curated`/`existing_label`/`existing_label_confidence` (does this
    candidate already exist in canonical_dataset.csv from a prior curation round -- see
    `_annotate_already_curated`). And per scorer, `match_classification__<name>`
    (positive/negative) if `scoring_bakeoff_report.csv` has a validated Youden threshold for that
    exact scorer + condition (positive-only vs positive-plus-exclusionary, auto-detected from
    whether an exclusionary lexicon was found) -- see `_lookup_youden_threshold`."""
    started_at = time.monotonic()
    lexicon_path = cfg.path("processed_dir") / "keyword_lexicon.csv"
    lexicon_df = pd.read_csv(lexicon_path)
    lexicon_terms, term_weights = load_lexicon_terms_and_weights(lexicon_df)

    exclusionary_path = resolve_path(cfg.pipeline["keywords"]["exclusionary_lexicon"])
    exclusionary_terms: list[str] = []
    exclusionary_term_weights: dict[str, float] = {}
    if exclusionary_path.exists():
        exclusionary_df = pd.read_csv(exclusionary_path)
        exclusionary_terms, exclusionary_term_weights = load_lexicon_terms_and_weights(exclusionary_df)
    condition = "positive_plus_exclusionary_lexicon" if exclusionary_terms else "positive_lexicon_only"

    candidates_path = cfg.sampling_path("bulk_candidates")
    candidates = pd.read_csv(candidates_path, dtype=str)
    texts = (candidates["title"].fillna("") + ". " + candidates["abstract"].fillna("")).tolist()

    candidates["has_pmcid"] = candidates["pmcid"].notna() & (candidates["pmcid"] != "")

    canonical_path = cfg.path("canonical_dataset")
    if canonical_path.exists():
        existing_lookup = _build_existing_label_lookup(pd.read_csv(canonical_path, dtype=str))
        candidates = _annotate_already_curated(candidates, existing_lookup)
    else:
        candidates["already_curated"] = False
        candidates["existing_label"] = ""
        candidates["existing_label_confidence"] = ""

    bakeoff_report_path = cfg.path("processed_dir") / "scoring_bakeoff_report.csv"
    thresholds_used: dict[str, float] = {}

    names_to_run = list(SCORERS) if scorer_name == "all" else [scorer_name]
    for name in names_to_run:
        scorer = _build_scorer(name, term_weights, exclusionary_term_weights)
        scored = scorer.score_corpus(
            texts,
            lexicon_terms,
            exclusionary_terms=exclusionary_terms or None,
            exclusionary_weight=exclusionary_weight,
        )
        candidates[f"match_score__{name}"] = [s for s, _ in scored]
        candidates[f"matched_terms__{name}"] = [";".join(terms) for _, terms in scored]

        threshold = _lookup_youden_threshold(bakeoff_report_path, name, condition)
        if threshold is not None:
            thresholds_used[name] = threshold
            candidates[f"match_classification__{name}"] = [
                "positive" if s >= threshold else "negative" for s in candidates[f"match_score__{name}"]
            ]

    output_path = cfg.sampling_path("bulk_candidates_scored")
    candidates.to_csv(output_path, index=False)

    n_already_curated = int(candidates["already_curated"].sum())
    n_has_pmcid = int(candidates["has_pmcid"].sum())

    finish_step(
        "keywords.score-bulk-match",
        inputs=[lexicon_path, candidates_path]
        + ([exclusionary_path] if exclusionary_terms else [])
        + ([bakeoff_report_path] if thresholds_used else []),
        outputs=[output_path],
        params={
            "scorer": scorer_name,
            "exclusionary_weight": exclusionary_weight,
            "n_exclusionary_terms": len(exclusionary_terms),
            "condition": condition,
            "thresholds_used": thresholds_used,
        },
        notes=f"{len(candidates)} candidates scored; {n_already_curated} already curated in "
        f"canonical_dataset.csv ({n_already_curated / len(candidates) * 100:.1f}%); "
        f"{n_has_pmcid} have a PMCID ({n_has_pmcid / len(candidates) * 100:.1f}%)"
        + (
            f"; classified at threshold(s) {thresholds_used} (from Step 11's bake-off)"
            if thresholds_used
            else "; no classification column added -- run `keywords scoring-bakeoff` first for one"
        ),
        started_at=started_at,
    )


def _load_existing_ids(canonical_path: Path) -> set[str]:
    if not canonical_path.exists():
        return set()
    dataset = pd.read_csv(canonical_path, dtype=str)
    ids = set(dataset["pmcid"].dropna()) | set(dataset["pmid"].dropna()) | set(dataset["doi"].dropna())
    return ids


def _merge_new_candidates_into_canonical(cfg: PipelineConfig, new_records: list[RawRecord]) -> int:
    """Filters out anything already present (by pmcid/pmid/doi), consolidates the remaining new
    batch (handles duplicates within the batch itself), and appends to canonical_dataset.csv --
    this is what makes a freshly sampled/fetched candidate pool show up in the curation queue."""
    canonical_path = cfg.path("canonical_dataset")
    existing_ids = _load_existing_ids(canonical_path)

    fresh = [r for r in new_records if not ({r.pmcid, r.pmid, r.doi} & existing_ids)]
    if not fresh:
        return 0

    new_canonical = consolidate(fresh)
    new_df = to_dataframe(new_canonical)

    if canonical_path.exists():
        existing_df = pd.read_csv(canonical_path, dtype=str)
        combined = pd.concat([existing_df, new_df], ignore_index=True)
    else:
        combined = new_df
    combined.to_csv(canonical_path, index=False)
    return len(new_canonical)


def step_sampling_stratify(cfg: PipelineConfig) -> None:
    started_at = time.monotonic()
    scored_path = cfg.sampling_path("bulk_candidates_scored")
    df = pd.read_csv(scored_path, dtype=str)

    score_cols = [c for c in df.columns if c.startswith("match_score__")]
    if not score_cols:
        raise ValueError(f"No match_score__* column found in {scored_path} -- run score-bulk-match first.")
    score_col = score_cols[0]
    df[score_col] = df[score_col].astype(float)
    df["year"] = pd.to_numeric(df["year"], errors="coerce")

    strata_cfg = cfg.sampling.get("strata", {})
    strata_df = build_strata(
        df,
        score_col=score_col,
        n_score_bands=strata_cfg.get("n_score_bands", 4),
        top_n_journals=strata_cfg.get("top_n_journals", 15),
        year_bucket_width=strata_cfg.get("year_bucket_width", 5),
    )
    strata_cols = [f"match_score_band__{score_col}", "journal_bucket", "year_bucket"]

    sampling_cfg = cfg.sampling.get("sampling", {})
    sampled, report = stratified_sample(
        strata_df,
        strata_cols,
        cap_per_stratum=sampling_cfg.get("cap_per_stratum", 10),
        random_state=sampling_cfg.get("random_state", 42),
    )

    pool_path = cfg.sampling_path("stratified_candidate_pool")
    report_path = cfg.sampling_path("stratum_report")
    sampled.to_csv(pool_path, index=False)
    report.to_csv(report_path, index=False)
    print(report.to_string(index=False))

    new_records = dataframe_to_raw_records(sampled)
    n_added = _merge_new_candidates_into_canonical(cfg, new_records)

    finish_step(
        "sampling.stratify",
        inputs=[scored_path],
        outputs=[pool_path, report_path],
        params={"strata_cols": strata_cols, "cap_per_stratum": sampling_cfg.get("cap_per_stratum", 10)},
        notes=f"{len(sampled)} sampled, {n_added} new records merged into canonical_dataset.csv "
        "for curation (rest were already present)",
        started_at=started_at,
    )


def step_ingest_fetch_clear_negatives(
    cfg: PipelineConfig, year_from: int, year_to: int, sample_size: int
) -> None:
    started_at = time.monotonic()
    epmc_cfg = cfg.sources.get("epmc", {})
    client = EpmcClient(
        base_url=epmc_cfg.get("base_url", "https://www.ebi.ac.uk/europepmc/webservices/rest"),
        page_size=epmc_cfg.get("page_size", 100),
        max_retries=epmc_cfg.get("max_retries", 5),
        backoff_factor=epmc_cfg.get("backoff_factor", 1.5),
    )
    try:
        df = fetch_clear_negatives(client, year_from, year_to, sample_size)
    finally:
        client.close()

    output_path = cfg.sampling_path("clear_negative_candidates")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_path, index=False)

    new_records = dataframe_to_raw_records(df)
    n_added = _merge_new_candidates_into_canonical(cfg, new_records)

    finish_step(
        "ingest.fetch-clear-negatives",
        inputs=[],
        outputs=[output_path],
        params={"year_from": year_from, "year_to": year_to, "sample_size": sample_size},
        notes=f"{len(df)} sampled, {n_added} new records merged into canonical_dataset.csv for curation",
        started_at=started_at,
    )


STEP_FUNCS = {
    "ingest": step_ingest_load_sources,
    "enrich": step_ingest_enrich_metadata,
    "dedupe": step_dedupe_consolidate,
    "manifest": step_fulltext_build_manifest,
    "tfidf": step_keywords_tfidf,
    "keybert": step_keywords_keybert,
    "build-lexicon": step_keywords_build_lexicon,
    "lexicon-stats": step_keywords_lexicon_stats,
    "scoring-bakeoff": step_keywords_scoring_bakeoff,
    "bulk-match-build-candidates": step_bulk_match_build_candidates,
    "sampling-stratify": step_sampling_stratify,
}


def run_steps(cfg: PipelineConfig, steps: list[str]) -> None:
    for step in steps:
        if step not in STEP_FUNCS:
            raise ValueError(f"Unknown step '{step}'. Valid steps: {list(STEP_FUNCS)}")
        STEP_FUNCS[step](cfg)
