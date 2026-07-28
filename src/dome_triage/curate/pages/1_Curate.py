"""Main Positive/Negative/Undeterminable/Skip curation queue -- ports curation.ipynb's
CurationInterface interaction pattern (see curate/state.py) into a Streamlit page.

The decision radio lives OUTSIDE the form so picking it reruns the page immediately -- needed so
`close_negative_reason` (configs/curation_features.yaml) only appears once "negative" is picked.
Everything else (tag/notes/structured features/submit) lives inside one st.form so it submits
atomically (Streamlit reruns the whole script per interaction, unlike ipywidgets' persistent
callbacks, so batching avoids partial-state bugs).
"""

from __future__ import annotations

import json

import streamlit as st
import yaml

from dome_triage.config import resolve_path
from dome_triage.curate.streamlit_helpers import get_session

st.set_page_config(page_title="Curate", layout="wide")
st.title("Curate")

if not st.session_state.get("curator_name"):
    st.warning("Set your curator name on the Home page first.")
    st.stop()

session = get_session()
record = session.current_record()

if record is None:
    st.success("No records left to curate.")
    st.stop()

st.caption(f"{session.remaining()} of {session.total()} remaining")
st.subheader(record.get("title") or "(no title)")
st.caption(f"{record.get('journal') or ''}  ·  {record.get('year') or ''}")

mesh_raw = record.get("mesh_headings")
if isinstance(mesh_raw, str) and mesh_raw.strip() not in ("", "[]"):
    try:
        mesh_list = json.loads(mesh_raw)
    except json.JSONDecodeError:
        mesh_list = []
    if mesh_list:
        st.caption(f"**MeSH:** {', '.join(mesh_list)}")

with st.container(height=300):
    st.markdown(record.get("abstract") or "*(no abstract available)*", unsafe_allow_html=True)

decision = st.radio(
    "Decision", ["positive", "negative", "undeterminable", "skipped"], horizontal=True
)

_features_path = resolve_path("configs/curation_features.yaml")
_features_config = (
    yaml.safe_load(_features_path.read_text()).get("features", [])
    if _features_path.exists()
    else []
)

with st.form("curation_form", clear_on_submit=True):
    tag = st.selectbox("Tag (optional)", ["", "uncertain", "close_negative"])
    notes = st.text_area("Notes")

    feature_values: dict = {}
    for feature in _features_config:
        shown_when = feature.get("shown_when_decision")
        if shown_when and shown_when != decision:
            continue
        if feature["type"] == "bool":
            feature_values[feature["key"]] = st.checkbox(feature["label"])
        elif feature["type"] == "select":
            feature_values[feature["key"]] = st.selectbox(
                feature["label"], [""] + feature["options"]
            )

    submitted = st.form_submit_button("Submit")

if submitted:
    features = {k: v for k, v in feature_values.items() if v not in (None, "", False)}
    session.record_decision(decision, tag=tag or None, notes=notes, features=features or None)
    st.rerun()
