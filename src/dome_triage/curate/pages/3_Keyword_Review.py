"""Human review checkpoint for the TF-IDF+KeyBERT candidate keyword lexicon -- the "keyword
trawl" step from the original plan. Approve/reject/edit candidate terms via an editable table;
approved terms become data/processed/keyword_lexicon.csv (see keywords/lexicon.py).
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from dome_triage.config import resolve_path
from dome_triage.curate.streamlit_helpers import get_config

st.set_page_config(page_title="Keyword Review", layout="wide")
st.title("Keyword Review")

cfg = get_config()
candidates_path = resolve_path(cfg.pipeline["keywords"]["candidates"])
lexicon_path = resolve_path(cfg.pipeline["keywords"]["lexicon"])

if not candidates_path.exists():
    st.info(
        "No keyword_lexicon_candidates.csv yet -- run `dome-triage keywords build-lexicon` first."
    )
    st.stop()

df = pd.read_csv(candidates_path)
edited = st.data_editor(
    df,
    column_config={
        "review_status": st.column_config.SelectboxColumn(
            options=["pending", "approved", "rejected"]
        ),
    },
    num_rows="fixed",
    use_container_width=True,
    height=600,
)

if st.button("Save reviewed lexicon"):
    approved = edited[edited["review_status"] == "approved"]
    lexicon_path.parent.mkdir(parents=True, exist_ok=True)
    approved.to_csv(lexicon_path, index=False)
    edited.to_csv(candidates_path, index=False)
    st.success(f"Saved {len(approved)} approved terms to {lexicon_path}")
