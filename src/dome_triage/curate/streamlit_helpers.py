"""Streamlit-specific helpers shared across curate/app.py and curate/pages/*.py. Kept separate
from state.py so CurationSession itself has no Streamlit import and stays unit-testable."""

from __future__ import annotations

import streamlit as st

from dome_triage.config import PipelineConfig, resolve_path
from dome_triage.curate.state import CurationSession
from dome_triage.curate.term_review_state import TermReviewSession


@st.cache_resource
def get_config() -> PipelineConfig:
    return PipelineConfig()


def get_session() -> CurationSession:
    cfg = get_config()
    curator = st.session_state.get("curator_name") or cfg.pipeline["curation"]["default_curator"]

    needs_new_session = (
        "curation_session" not in st.session_state
        or st.session_state.get("_curator_for_session") != curator
    )
    if needs_new_session:
        st.session_state["curation_session"] = CurationSession(
            dataset_path=cfg.path("canonical_dataset"),
            events_path=resolve_path(cfg.pipeline["curation"]["events_log"]),
            curator=curator,
        )
        st.session_state["_curator_for_session"] = curator
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
