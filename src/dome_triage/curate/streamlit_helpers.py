"""Streamlit-specific helpers shared across curate/app.py and curate/pages/*.py. Kept separate
from state.py so CurationSession itself has no Streamlit import and stays unit-testable."""

from __future__ import annotations

import streamlit as st

from dome_triage.config import PipelineConfig, resolve_path
from dome_triage.curate.state import CurationSession


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
