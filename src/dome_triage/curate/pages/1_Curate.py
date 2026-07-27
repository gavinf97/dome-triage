"""Main YES/NO/Skip curation queue -- ports curation.ipynb's CurationInterface interaction
pattern (see curate/state.py) into a Streamlit form so decision+tag+notes submit atomically
(Streamlit reruns the whole script per interaction, unlike ipywidgets' persistent callbacks, so
batching into one st.form avoids partial-state bugs).
"""

from __future__ import annotations

import streamlit as st

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

with st.container(height=300):
    st.markdown(record.get("abstract") or "*(no abstract available)*", unsafe_allow_html=True)

with st.form("curation_form", clear_on_submit=True):
    decision = st.radio("Decision", ["positive", "negative", "skipped"], horizontal=True)
    tag = st.selectbox("Tag (optional)", ["", "uncertain", "close_negative"])
    notes = st.text_area("Notes")
    submitted = st.form_submit_button("Submit")

if submitted:
    session.record_decision(decision, tag=tag or None, notes=notes)
    st.rerun()
