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
from dome_triage.curate.streamlit_helpers import get_filter_options, get_session

st.set_page_config(page_title="Curate", layout="wide")
st.title("Curate")

if not st.session_state.get("curator_name"):
    st.warning("Set your curator name on the Home page first.")
    st.stop()

toggle_col1, toggle_col2 = st.columns(2)
include_already_labeled = toggle_col1.checkbox(
    "Include already-curated records (redo / re-review)",
    value=False,
    help="Off by default: records already trusted from a prior curation round "
    "(label_confidence human_curated or registry_confirmed) are excluded from the queue -- "
    "they're settled ground truth, not new. Turn on to deliberately re-review them anyway.",
)
require_pmcid = toggle_col2.checkbox(
    "Only show records with full text available (has PMCID)",
    value=False,
)

_N_SCORE_BANDS = 4
_TOP_N_JOURNALS = 15
_filter_options = get_filter_options(top_n_journals=_TOP_N_JOURNALS)

with st.expander("Filters (diverse strata, top journals, year, BM25 classification)"):
    f_col1, f_col2 = st.columns(2)
    score_band = f_col1.multiselect(
        "Match-score band (within the current queue)",
        options=list(range(_N_SCORE_BANDS)),
        format_func=lambda i: f"Q{i + 1}" + (" (highest)" if i == _N_SCORE_BANDS - 1 else " (lowest)" if i == 0 else ""),
        help="Quartiles of match_score__bm25, computed fresh over whatever's currently in the "
        "queue -- not replaying Step 13's original 745k-pool-wide bands, which would be less "
        "useful once the queue is already a small, pre-stratified subset. Records with no BM25 "
        "score at all (e.g. never went through Step 12) are excluded when this filter is active.",
    )
    journals = f_col2.multiselect(
        "Journal (top journals by volume; select nothing for all)",
        options=[*_filter_options["journals"], "other"],
    )
    f_col3, f_col4 = st.columns(2)
    year_range = f_col3.slider(
        "Year range",
        min_value=_filter_options["year_min"],
        max_value=_filter_options["year_max"],
        value=(_filter_options["year_min"], _filter_options["year_max"]),
        help="Collapse both handles to the same year to pick a single year.",
    )
    classification = f_col4.multiselect(
        "BM25 classification",
        options=["positive", "negative"],
    )
    needs_screening_only = st.checkbox(
        "Only show clear-negative candidates flagged for extra scrutiny (Step 14b)",
        value=False,
        help="A 'clear negative' (fetched specifically for NOT mentioning AI/ML terms) that "
        "still scored above the validated lexicon threshold -- worth a closer look before "
        "trusting it as a genuine negative.",
    )

session = get_session(
    include_already_labeled=include_already_labeled,
    require_pmcid=require_pmcid,
    score_band=score_band or None,
    journals=journals or None,
    year_range=year_range if year_range != (_filter_options["year_min"], _filter_options["year_max"]) else None,
    classification=classification or None,
    needs_screening_only=needs_screening_only,
)

with st.sidebar.expander("Diversity tracker", expanded=False):
    stats = session.diversity_stats()
    st.metric(
        "Journal coverage (confirmed pos/neg)",
        f"{stats['n_journals_covered']} / {stats['n_journals_total']}",
        f"{stats['journal_coverage_pct']:.1f}%",
    )
    if not stats["per_year_counts"].empty:
        st.caption("Positive/negative decisions by year")
        st.bar_chart(stats["per_year_counts"])
    if not stats["per_journal_counts"].empty:
        st.caption("Positive/negative decisions by journal (top by volume)")
        st.dataframe(stats["per_journal_counts"].sort_values(by=list(stats["per_journal_counts"].columns), ascending=False).head(20))

record = session.current_record()

if record is None:
    st.success("No records left to curate.")
    st.stop()

st.caption(f"{session.remaining()} of {session.total()} remaining (this filtered view)")

if journals and len(journals) == 1:
    # Direct, contextual feedback right where it matters -- about to decide on a paper from this
    # journal, not buried in the sidebar.
    j = journals[0]
    per_journal = session.diversity_stats()["per_journal_counts"]
    if j in per_journal.index:
        pos = int(per_journal.loc[j].get("positive", 0))
        neg = int(per_journal.loc[j].get("negative", 0))
        st.caption(f"**{j}** so far: {pos} positive / {neg} negative confirmed")

needs_screening = bool(record.get("needs_screening"))
if needs_screening:
    bulk_score = record.get("bulk_match_score")
    score_text = f"{float(bulk_score):.1f}" if bulk_score not in (None, "") else "?"
    st.warning(
        f"This clear-negative candidate scored {score_text} against the lexicon despite the "
        "AI/ML exclusion query used to fetch it -- double-check before confirming negative."
    )

st.markdown(
    f"### {record.get('title') or '(no title)'}", unsafe_allow_html=True
)
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

_tag_options = ["", "uncertain", "close_negative"]
if needs_screening:
    # Reuses the existing tag/features mechanism rather than a new event-log column -- see
    # bulk_scores.py's module docstring and Step 14b's docs for why.
    _tag_options += ["screening_confirmed_negative", "screening_reclassified"]

with st.form("curation_form", clear_on_submit=True):
    tag = st.selectbox("Tag (optional)", _tag_options)
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
