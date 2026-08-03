"""Streamlit-specific helpers shared across curate/app.py and curate/pages/*.py. Kept separate
from state.py so CurationSession itself has no Streamlit import and stays unit-testable."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from dome_triage.config import PipelineConfig, resolve_path
from dome_triage.curate.bulk_pool import load_bulk_pool
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


@st.cache_resource
def _cached_bulk_pool(path: str, mtime: float):
    """Same mtime-keyed `st.cache_resource` pattern as `_cached_bulk_score_lookup` above -- built
    once per app process, independent of whichever Curate-page filters are toggled. This is the
    larger of the two caches (title/abstract/journal/year/mesh alongside the score, not just the
    score) -- see `bulk_pool.py::load_bulk_pool`'s docstring for the read-cost tradeoff. A filter
    click must never re-read the underlying ~745k-row file a second time."""
    return load_bulk_pool(Path(path))


def get_bulk_pool():
    cfg = get_config()
    path = cfg.sampling_path("bulk_candidates_scored")
    mtime = path.stat().st_mtime if path.exists() else 0.0
    return _cached_bulk_pool(str(path), mtime)


def get_bulk_pool_score_bounds() -> tuple[float, float] | None:
    """(min, max) of `bulk_match_score` across the *entire* bulk pool -- for the Curate page's raw
    score-figure inputs when browsing that pool directly, so their bounds reflect the real data
    rather than an arbitrary guess. Cheap: `get_bulk_pool()` is already cached, this just reads two
    already-resident columns' min/max, no new I/O."""
    pool = get_bulk_pool()
    scores = pool["bulk_match_score"].dropna()
    if scores.empty:
        return None
    return float(scores.min()), float(scores.max())


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


def _bulk_pool_session_kwargs(cfg: PipelineConfig) -> dict:
    """Shared construction kwargs for a bulk-pool-backed session -- used by both
    `build_probe_session` and `get_session` below so the two stay consistent. `bulk_score_lookup`/
    `screening_lookup` are deliberately omitted (left at their None defaults): the bulk pool
    already carries its own `bulk_match_score`/`bulk_match_classification` columns natively (see
    `bulk_pool.py::load_bulk_pool`), so a second lookup-join would just recompute what's already
    in the frame."""
    scored_path = cfg.sampling_path("bulk_candidates_scored")
    return {
        "dataset_path": scored_path,
        "dataset_df": get_bulk_pool(),
        "sort_by_score_desc": True,
    }


def build_probe_session(
    include_already_labeled: bool = False,
    only_already_labeled: bool = False,
    require_pmcid: bool = False,
    classification: list | None = None,
    needs_screening_only: bool = False,
    queue_source: str = "canonical",
) -> CurationSession:
    """A CurationSession used only to compute score_band_summary()/year_bounds() for the Filters
    widgets *before* those widgets have a value to feed into the real, cached get_session() call
    below (score_band/journals/year_range are intentionally omitted from this probe's filters --
    neither method depends on them, see state.py). Kept in its OWN session_state cache slot,
    separate from get_session()'s, specifically so calling both with different keys in the same
    rerun never thrashes get_session()'s one slot into reconstructing the *real* browsing session
    pointlessly on every interaction.

    **Cached, not rebuilt every rerun** -- this used to be deliberately uncached, on the reasoning
    that reconstructing it was cheap since canonical_dataset.csv is small. That reasoning silently
    stopped being true the moment `queue_source="bulk_pool"` was added: probing the ~745k-row bulk
    pool runs `_scored_pool()`'s full filter chain (see state.py) on every single script rerun --
    not just when a filter genuinely changes -- and each of those runs leaves peak RSS that isn't
    reclaimed afterward (glibc doesn't return freed heap arenas to the OS). The *compounding* cost
    across a real, multi-interaction browsing session (not any one call) is what OOM-killed the
    `curate` container in real use, exit code 137 -- confirmed via `journalctl -k` for the earlier,
    smaller version of this same class of bug (see AGENTS.md's "Curate app performance" section).
    Caching this the same way get_session() already is closes that gap: the expensive rebuild now
    only happens when one of *this probe's own* inputs actually changes."""
    cfg = get_config()
    curator = _curator_name(cfg)
    key = (
        curator,
        include_already_labeled,
        only_already_labeled,
        require_pmcid,
        tuple(sorted(classification)) if classification else None,
        needs_screening_only,
        queue_source,
    )

    if st.session_state.get("_probe_session_key") != key:
        base_kwargs = dict(
            events_path=resolve_path(cfg.pipeline["curation"]["events_log"]),
            curator=curator,
            include_already_labeled=include_already_labeled,
            only_already_labeled=only_already_labeled,
            require_pmcid=require_pmcid,
            classification=classification,
            needs_screening_only=needs_screening_only,
        )
        if queue_source == "bulk_pool":
            session = CurationSession(**base_kwargs, **_bulk_pool_session_kwargs(cfg))
        else:
            session = CurationSession(
                **base_kwargs,
                dataset_path=cfg.path("canonical_dataset"),
                bulk_score_lookup=get_bulk_score_lookup(),
                screening_lookup=get_screening_lookup(),
            )
        st.session_state["probe_session"] = session
        st.session_state["_probe_session_key"] = key
    return st.session_state["probe_session"]


def get_session(
    include_already_labeled: bool = False,
    only_already_labeled: bool = False,
    require_pmcid: bool = False,
    score_band: list | None = None,
    journals: list | None = None,
    year_range: tuple | None = None,
    classification: list | None = None,
    needs_screening_only: bool = False,
    queue_source: str = "canonical",
    min_score: float | None = None,
    max_score: float | None = None,
) -> CurationSession:
    """Like get_term_review_session, the cache key must include every filter (not just the
    curator) -- they redefine which records are in the reviewable queue at all, not just how it's
    sorted/filtered client-side, so switching any of them must reconstruct fresh. This is cheap:
    `canonical_dataset.csv` is small (low thousands of rows) -- the expensive file
    (`bulk_candidates_scored.csv`) is isolated behind get_bulk_score_lookup()'s own independent
    cache above, so a filter tweak here never re-reads it. This is the *one* session that drives
    navigation state (_position/_frontier) -- use build_probe_session() above for anything that
    just needs read-only stats without disturbing this cache slot.

    `queue_source="bulk_pool"` browses the full ~745k-record bulk pool, ranked by BM25 score
    (`sort_by_score_desc=True`, see state.py), instead of being confined to Step 13's
    pre-stratified queue -- `min_score`/`max_score` narrow it to a chosen figure range rather than
    a quartile band. Reconstructing this session is still cheap even in bulk-pool mode: the
    ~745k-row frame itself is built once and cached (`get_bulk_pool()`, `st.cache_resource`,
    independent of this key) -- switching `min_score` here filters that already-resident frame,
    it never re-reads the underlying file."""
    cfg = get_config()
    curator = _curator_name(cfg)
    key = (
        curator,
        include_already_labeled,
        only_already_labeled,
        require_pmcid,
        tuple(sorted(score_band)) if score_band else None,
        tuple(sorted(journals)) if journals else None,
        year_range,
        tuple(sorted(classification)) if classification else None,
        needs_screening_only,
        queue_source,
        min_score,
        max_score,
    )

    needs_new_session = st.session_state.get("_curation_session_key") != key
    if needs_new_session:
        base_kwargs = dict(
            events_path=resolve_path(cfg.pipeline["curation"]["events_log"]),
            curator=curator,
            include_already_labeled=include_already_labeled,
            only_already_labeled=only_already_labeled,
            require_pmcid=require_pmcid,
            journals=journals,
            year_range=year_range,
            classification=classification,
            needs_screening_only=needs_screening_only,
            min_score=min_score,
            max_score=max_score,
        )
        if queue_source == "bulk_pool":
            st.session_state["curation_session"] = CurationSession(
                **base_kwargs, **_bulk_pool_session_kwargs(cfg)
            )
        else:
            st.session_state["curation_session"] = CurationSession(
                **base_kwargs,
                dataset_path=cfg.path("canonical_dataset"),
                bulk_score_lookup=get_bulk_score_lookup(),
                screening_lookup=get_screening_lookup(),
                score_band=score_band,
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
