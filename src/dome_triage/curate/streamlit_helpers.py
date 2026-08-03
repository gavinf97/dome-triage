"""Streamlit-specific helpers shared across curate/app.py and curate/pages/*.py. Kept separate
from state.py so CurationSession itself has no Streamlit import and stays unit-testable."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from dome_triage.config import PipelineConfig, resolve_path
from dome_triage.curate.bulk_scores import load_bulk_score_lookup, load_screening_lookup, load_youden_threshold
from dome_triage.curate.state import CurationSession
from dome_triage.curate.term_review_state import TermReviewSession


@st.cache_resource
def get_config() -> PipelineConfig:
    return PipelineConfig()


@st.cache_resource
def _cached_bulk_score_lookup(path: str, mtime: float) -> dict:
    """mtime-keyed, same precedent as 3_Keyword_Review.py's _load_candidates(path, mtime) --
    re-running `keywords score-bulk-match` invalidates this automatically. Built once, completely
    independent of whichever Curate-page filters are toggled (unlike get_session()'s cache key
    below) -- a filter click must never re-read a ~1.7GB file. Confirmed via live profiling this
    part was never the problem -- ~17s on the first real MISS, ~0s on every call after (the actual
    incident was downstream, in how the resulting ~2.07M-entry lookup got used per-call -- see
    bulk_scores.py::annotate_bulk_scores and state.py::CurationSession._scored_pool)."""
    return load_bulk_score_lookup(Path(path))


@st.cache_resource
def _cached_screening_lookup(path: str, mtime: float) -> dict:
    return load_screening_lookup(Path(path))


def get_bulk_score_lookup() -> dict:
    cfg = get_config()
    path = cfg.sampling_path("bulk_candidates_scored")
    mtime = path.stat().st_mtime if path.exists() else 0.0
    return _cached_bulk_score_lookup(str(path), mtime)


@st.cache_data
def _cached_filter_options(path: str, mtime: float) -> dict:
    """Populates the Curate page's journal/year widget options from `canonical_dataset.csv`
    directly -- cheap (small file, two columns), and deliberately reads the file directly rather
    than through a constructed CurationSession, so the options list never itself depends on
    whichever filters are currently selected (that would make the widgets move under the user's
    cursor). `journals` is *every* distinct journal in the dataset, sorted most-common-first --
    not a top-N shortlist -- so the journal picker is a real search/autocomplete over the whole
    corpus (Streamlit's multiselect already filters options as you type; the earlier top-15-only
    version was the actual complaint, not the widget itself)."""
    df = pd.read_csv(path, usecols=["journal", "year"], dtype=str)
    years = pd.to_numeric(df["year"], errors="coerce").dropna()
    return {
        "journals": df["journal"].value_counts().index.tolist(),
        "year_min": int(years.min()) if not years.empty else 2000,
        "year_max": int(years.max()) if not years.empty else 2026,
    }


def get_filter_options() -> dict:
    cfg = get_config()
    path = cfg.path("canonical_dataset")
    mtime = path.stat().st_mtime if path.exists() else 0.0
    return _cached_filter_options(str(path), mtime)


def get_screening_lookup() -> dict:
    cfg = get_config()
    path = cfg.sampling_path("clear_negative_candidates_screened")
    mtime = path.stat().st_mtime if path.exists() else 0.0
    return _cached_screening_lookup(str(path), mtime)


@st.cache_data
def _cached_youden_threshold(path: str, mtime: float) -> float | None:
    return load_youden_threshold(Path(path))


def get_youden_threshold() -> float | None:
    cfg = get_config()
    path = cfg.path("processed_dir") / "scoring_bakeoff_report.csv"
    mtime = path.stat().st_mtime if path.exists() else 0.0
    return _cached_youden_threshold(str(path), mtime)


def _curator_name(cfg: PipelineConfig) -> str:
    return st.session_state.get("curator_name") or cfg.pipeline["curation"]["default_curator"]


def build_probe_session(
    include_already_labeled: bool = False,
    require_pmcid: bool = False,
    classification: list | None = None,
    needs_screening_only: bool = False,
) -> CurationSession:
    """A throwaway, uncached CurationSession -- deliberately built fresh every call, bypassing
    get_session()'s single session-state cache slot entirely. Used only to compute
    score_band_summary() for the score-band filter widget's labels *before* the widget itself has
    a value to feed into the real, cached get_session() call below (score_band/journals/year_range
    are intentionally omitted here -- score_band_summary() doesn't depend on them anyway, see
    state.py). Reconstructing this every rerun is cheap (canonical_dataset.csv is small); calling
    get_session() twice with different keys in the same rerun would instead thrash its one cache
    slot, reconstructing the *real* session pointlessly on every interaction. Confirmed cheap by
    live profiling once `annotate_bulk_scores`'s per-call cost and `_scored_pool()`'s
    within-instance redundancy were both fixed (see bulk_scores.py and state.py) -- before those
    fixes, "cheap" was wrong: this alone cost 9-10s per call from `annotate_bulk_scores` and up to
    ~30s once `_scored_pool()`'s redundant recomputation stacked on top."""
    cfg = get_config()
    return CurationSession(
        dataset_path=cfg.path("canonical_dataset"),
        events_path=resolve_path(cfg.pipeline["curation"]["events_log"]),
        curator=_curator_name(cfg),
        include_already_labeled=include_already_labeled,
        require_pmcid=require_pmcid,
        bulk_score_lookup=get_bulk_score_lookup(),
        screening_lookup=get_screening_lookup(),
        classification=classification,
        needs_screening_only=needs_screening_only,
    )


def get_session(
    include_already_labeled: bool = False,
    require_pmcid: bool = False,
    score_band: list | None = None,
    journals: list | None = None,
    year_range: tuple | None = None,
    classification: list | None = None,
    needs_screening_only: bool = False,
) -> CurationSession:
    """Like get_term_review_session, the cache key must include every filter (not just the
    curator) -- they redefine which records are in the reviewable queue at all, not just how it's
    sorted/filtered client-side, so switching any of them must reconstruct fresh. This is cheap:
    `canonical_dataset.csv` is small (low thousands of rows) -- the expensive file
    (`bulk_candidates_scored.csv`) is isolated behind get_bulk_score_lookup()'s own independent
    cache above, so a filter tweak here never re-reads it. This is the *one* session that drives
    navigation state (_position/_frontier) -- use build_probe_session() above for anything that
    just needs read-only stats without disturbing this cache slot."""
    cfg = get_config()
    curator = _curator_name(cfg)
    key = (
        curator,
        include_already_labeled,
        require_pmcid,
        tuple(sorted(score_band)) if score_band else None,
        tuple(sorted(journals)) if journals else None,
        year_range,
        tuple(sorted(classification)) if classification else None,
        needs_screening_only,
    )

    needs_new_session = st.session_state.get("_curation_session_key") != key
    if needs_new_session:
        st.session_state["curation_session"] = CurationSession(
            dataset_path=cfg.path("canonical_dataset"),
            events_path=resolve_path(cfg.pipeline["curation"]["events_log"]),
            curator=curator,
            include_already_labeled=include_already_labeled,
            require_pmcid=require_pmcid,
            bulk_score_lookup=get_bulk_score_lookup(),
            screening_lookup=get_screening_lookup(),
            score_band=score_band,
            journals=journals,
            year_range=year_range,
            classification=classification,
            needs_screening_only=needs_screening_only,
        )
        st.session_state["_curation_session_key"] = key
    return st.session_state["curation_session"]


def get_term_review_session(
    queue_source: str,
    min_discriminative_score: float,
    min_document_frequency: float,
    max_discriminative_score: float,
    max_terms: int,
) -> TermReviewSession:
    """Unlike get_session()'s queue (fixed once built), TermReviewSession's queue is
    live-redefined by the threshold/cap widgets on the Keyword Review page -- so the
    session-state cache key must include them, not just the curator. A single cached slot
    (keyed on queue_source too) deliberately means switching piles always reconstructs fresh from
    disk -- decisions are global now (see term_review_state.py), so a stale cached session in the
    *other* pile could otherwise show outdated all_time_counts() or a queue containing a term
    that was just decided elsewhere."""
    cfg = get_config()
    curator = st.session_state.get("curator_name") or cfg.pipeline["curation"]["default_curator"]
    key = (
        curator,
        queue_source,
        min_discriminative_score,
        min_document_frequency,
        max_discriminative_score,
        max_terms,
    )

    if st.session_state.get("_term_review_key") != key:
        st.session_state["term_review_session"] = TermReviewSession(
            candidates_path=resolve_path(cfg.pipeline["keywords"]["candidates"]),
            events_path=resolve_path(cfg.pipeline["keyword_review"]["events_log"]),
            queue_source=queue_source,
            curator=curator,
            min_discriminative_score=min_discriminative_score,
            min_document_frequency=min_document_frequency,
            max_discriminative_score=max_discriminative_score,
            max_terms=max_terms,
        )
        st.session_state["_term_review_key"] = key
    return st.session_state["term_review_session"]
