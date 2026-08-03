"""Main Positive/Negative/Undeterminable/Skip curation queue -- ports curation.ipynb's
CurationInterface interaction pattern (see curate/state.py) into a Streamlit page.

Keyboard-first by design (P/N/U/S submit and advance immediately -- no staged "pick a decision,
then submit" step, since that's slower for the rapid-review workload this page exists for).
Decision buttons use `on_click` callbacks (not a post-hoc `if button:` check) specifically because
that's the only Streamlit-supported way to clear the Notes widget for the next record without
hitting "cannot modify a widget after it's instantiated" -- callbacks run in a phase before the
widget is re-instantiated on the next rerun. The keyboard-shortcut script below drives these same
buttons by simulating a real DOM click, so it doesn't need its own Python-side handling at all.
"""

from __future__ import annotations

import json

import streamlit as st
import yaml

from dome_triage.config import resolve_path
from dome_triage.curate.streamlit_helpers import (
    build_probe_session,
    get_filter_options,
    get_session,
    get_youden_threshold,
)

st.set_page_config(page_title="Curate", layout="wide")
st.title("Curate")

if not st.session_state.get("curator_name"):
    st.warning("Set your curator name on the Home page first.")
    st.stop()

# ---------------------------------------------------------------------------------------------
# Filters -- collapsed by default so the paper under review stays the focus; state persists once
# you collapse it back down yourself.
# ---------------------------------------------------------------------------------------------
with st.expander("Filters", expanded=False):
    toggle_col1, toggle_col2 = st.columns(2)
    include_already_labeled = toggle_col1.checkbox(
        "Also show already-curated records (from the ORIGINAL curation effort, for re-checking)",
        value=False,
        help="Off by default: records already trusted from a prior curation round -- "
        "DOME_Top_Curate, the DOME registry, or a decision you already materialized through this "
        "app -- are settled ground truth and excluded from the queue. Turn this on only if you "
        "deliberately want to revisit and possibly change some of those original decisions.",
    )
    require_pmcid = toggle_col2.checkbox(
        "Only show records with full text available (has PMCID)", value=False
    )

    classification = st.multiselect(
        "BM25 classification (Step 12)", options=["positive", "negative"]
    )
    needs_screening_only = st.checkbox(
        "Only show clear-negative candidates flagged for extra scrutiny (Step 14b)",
        value=False,
        help="A 'clear negative' (fetched specifically for NOT mentioning AI/ML terms) that "
        "still scored above the validated lexicon threshold -- worth a closer look before "
        "trusting it as a genuine negative.",
    )

    # Probe session: same base filters as above, but never touches get_session()'s cache slot --
    # only used to compute real score-range/curated-so-far numbers for the band widget's labels.
    probe = build_probe_session(
        include_already_labeled=include_already_labeled,
        require_pmcid=require_pmcid,
        classification=classification or None,
        needs_screening_only=needs_screening_only,
    )
    band_summary = probe.score_band_summary()
    _n_bands = len(band_summary)

    def _format_band(band_idx: int) -> str:
        info = next((b for b in band_summary if b["band"] == band_idx), None)
        if info is None:
            return f"Q{band_idx + 1}"
        extreme = " (lowest)" if band_idx == 0 else " (highest)" if band_idx == _n_bands - 1 else ""
        return (
            f"Q{band_idx + 1}{extreme}: BM25 {info['min_score']:.1f}-{info['max_score']:.1f} "
            f"-- {info['confirmed']}/{info['total']} curated"
        )

    score_band = st.multiselect(
        "Match-score band (BM25)",
        options=[b["band"] for b in band_summary],
        format_func=_format_band,
        help="Quartiles of match_score__bm25 (Q1 = lowest scores, Q4 = highest), computed fresh "
        "over whatever the other filters above currently leave in the queue -- not replaying "
        "Step 13's original 745k-pool-wide bands, which would be less useful now that the queue "
        "is already a small, pre-stratified subset. 'X/Y curated' = how many of that band's "
        "records already have a confirmed decision, out of the band's total.",
    )

    _filter_options = get_filter_options()
    journals = st.multiselect(
        "Journal (type to search -- every journal in the dataset, not just a top-N shortlist)",
        options=_filter_options["journals"],
    )

    # Year bounds come from the probe (the currently-filtered population), not the whole dataset
    # -- e.g. once you've filtered to classification=positive, the slider should only span years
    # actually present among positive-classified records, not the full corpus's range.
    _year_min, _year_max = probe.year_bounds() or (_filter_options["year_min"], _filter_options["year_max"])
    year_range = st.slider(
        "Year range (bounds reflect the filters above, not the whole dataset)",
        min_value=_year_min,
        max_value=_year_max,
        value=(_year_min, _year_max),
        help="Collapse both handles to the same year to pick a single year.",
    )

session = get_session(
    include_already_labeled=include_already_labeled,
    require_pmcid=require_pmcid,
    score_band=score_band or None,
    journals=journals or None,
    year_range=year_range if year_range != (_year_min, _year_max) else None,
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
        st.dataframe(
            stats["per_journal_counts"]
            .sort_values(by=list(stats["per_journal_counts"].columns), ascending=False)
            .head(20)
        )

# ---------------------------------------------------------------------------------------------
# Progress + navigation. Uses `on_click` rather than `if button:` + `st.rerun()`, for two separate
# reasons that both matter:
#   - No st.rerun(): Streamlit already reruns the script on any widget click, so an explicit one
#     forces a *second* full execution (re-reading both CSVs, rebuilding the scored pool) for zero
#     gain -- measured live as an exact doubling of the page's wall time.
#   - on_click, not `if button:`: callbacks run *before* the script body, so the move is already
#     applied when these buttons compute their own `disabled` state below. With `if button:` the
#     move happens after they've rendered, leaving both buttons a full interaction stale (clicking
#     Forward off position 0 correctly showed the next paper but left "< Back" greyed out).
# ---------------------------------------------------------------------------------------------
nav_prog, nav_back, nav_fwd = st.columns([6, 1, 1])
nav_prog.caption(f"{session.remaining()} of {session.total()} remaining (this filtered view)")
nav_back.button(
    "< Back", disabled=not session.can_go_back(), on_click=session.go_back, use_container_width=True
)
nav_fwd.button(
    "Forward >",
    disabled=not session.can_go_forward(),
    on_click=session.go_forward,
    use_container_width=True,
)

record = session.current_record()

if record is None:
    st.success("No records left to curate.")
    st.stop()

prior_decision = session.current_record_prior_decision()
if prior_decision:
    st.info(f"You already marked this record **{prior_decision}** this session. Reviewing again.")

if journals and len(journals) == 1:
    j = journals[0]
    per_journal = stats["per_journal_counts"]
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

# ---------------------------------------------------------------------------------------------
# Paper display
# ---------------------------------------------------------------------------------------------
st.markdown(f"### {record.get('title') or '(no title)'}", unsafe_allow_html=True)

def _display_year(value) -> str:
    """Real years in canonical_dataset.csv are string-formatted floats ("2025.0") -- a pre-existing
    artifact of the consolidate pipeline's CSV round-tripping (see sampling/stratified.py, which
    handles the same thing). Rendering that raw put "Year: 2025.0" on every single paper."""
    try:
        return str(int(float(value)))
    except (TypeError, ValueError):
        return "(unknown)"


meta_col1, meta_col2 = st.columns(2)
meta_col1.markdown(f"**Journal:** {record.get('journal') or '(unknown)'}", unsafe_allow_html=True)
meta_col2.markdown(f"**Year:** {_display_year(record.get('year'))}")

bm25_score = record.get("bulk_match_score")
bm25_classification = record.get("bulk_match_classification")
if bm25_score not in (None, "", "nan") and str(bm25_score) != "nan":
    threshold = get_youden_threshold()
    threshold_text = (
        f"Classified **{bm25_classification or '(unscored)'}** because the score is "
        f"{'>=' if bm25_classification == 'positive' else '<'} the validated Youden threshold "
        f"of {threshold:.1f} (Step 11's bake-off, bm25 + exclusionary lexicon). Higher score = "
        "stronger lexicon match; this is a ranking signal to help triage, not a verdict -- your "
        "decision is what actually counts."
        if threshold is not None
        else "No validated classification threshold found yet (run `keywords scoring-bakeoff`)."
    )
    st.metric(
        "BM25 match score",
        f"{float(bm25_score):.1f}  ({bm25_classification or 'unscored'})",
        help=threshold_text,
    )

mesh_raw = record.get("mesh_headings")
if isinstance(mesh_raw, str) and mesh_raw.strip() not in ("", "[]"):
    try:
        mesh_list = json.loads(mesh_raw)
    except json.JSONDecodeError:
        mesh_list = []
    if mesh_list:
        st.markdown(f"**MeSH terms:** {', '.join(mesh_list)}")

with st.container(height=300):
    st.markdown(record.get("abstract") or "*(no abstract available)*", unsafe_allow_html=True)

# ---------------------------------------------------------------------------------------------
# Decision -- P/N/U/S all submit immediately and advance (see module docstring for why there's no
# separate staged-decision step). Notes/optional feature widgets are read at submit time via
# their session_state keys, not through an st.form.
# ---------------------------------------------------------------------------------------------
_features_path = resolve_path("configs/curation_features.yaml")
_features_config = (
    yaml.safe_load(_features_path.read_text()).get("features", [])
    if _features_path.exists()
    else []
)

st.text_area("Notes (optional)", key="curate_notes")
for feature in _features_config:
    if feature["type"] == "bool":
        st.checkbox(feature["label"], key=f"curate_feat_{feature['key']}")
    elif feature["type"] == "select":
        st.selectbox(feature["label"], [""] + feature["options"], key=f"curate_feat_{feature['key']}")


def _submit(decision: str):
    def _callback():
        features = {}
        for feature in _features_config:
            value = st.session_state.get(f"curate_feat_{feature['key']}")
            if value not in (None, "", False):
                features[feature["key"]] = value
            st.session_state[f"curate_feat_{feature['key']}"] = "" if feature["type"] == "select" else False
        notes = st.session_state.get("curate_notes", "")
        session.record_decision(decision, notes=notes, features=features or None)
        st.session_state["curate_notes"] = ""

    return _callback


btn_col1, btn_col2, btn_col3, btn_col4 = st.columns(4)
btn_col1.button(
    "Positive (P)", on_click=_submit("positive"), use_container_width=True, type="primary"
)
btn_col2.button("Negative (N)", on_click=_submit("negative"), use_container_width=True)
btn_col3.button("Undeterminable (U)", on_click=_submit("undeterminable"), use_container_width=True)
btn_col4.button("Skip (S)", on_click=_submit("skipped"), use_container_width=True)

# ---------------------------------------------------------------------------------------------
# Keyboard shortcuts: P/N/U/S trigger the matching button above by simulating a real click on its
# underlying DOM element (this is the only way to drive a server-side on_click callback from
# client-side JS -- there's no direct Python hook to bind to). Guarded on a flag stashed on
# `window.parent` (the actual browser tab, not this component's own iframe) so the listener is
# attached exactly once for the page's lifetime -- st.iframe re-runs this script on every
# Streamlit rerun (i.e. after every decision), and without the guard each rerun would stack
# another duplicate listener on the parent document, eventually firing one keypress N times.
# Ignored entirely while focus is inside a text input/textarea (typing "n" in Notes must type a
# letter, not submit "negative").
# ---------------------------------------------------------------------------------------------
st.iframe(
    """
    <script>
    (function() {
        const doc = window.parent.document;
        if (window.parent._domeTriageShortcutsAttached) { return; }
        window.parent._domeTriageShortcutsAttached = true;

        function findButton(labelStart) {
            const buttons = Array.from(doc.querySelectorAll('button'));
            return buttons.find(b => b.innerText.trim().startsWith(labelStart));
        }

        doc.addEventListener('keydown', function(e) {
            const active = doc.activeElement;
            const isTyping = active && (
                active.tagName === 'TEXTAREA' ||
                active.tagName === 'INPUT' ||
                active.isContentEditable
            );
            if (isTyping) { return; }

            const keyMap = {
                'p': 'Positive (P)', 'n': 'Negative (N)',
                'u': 'Undeterminable (U)', 's': 'Skip (S)',
            };
            const label = keyMap[e.key.toLowerCase()];
            if (!label) { return; }
            const btn = findButton(label);
            if (btn) { btn.click(); e.preventDefault(); }
        });
    })();
    </script>
    """,
    height=1,  # st.iframe rejects 0 (StreamlitInvalidHeightError) -- 1px is the smallest valid,
    # effectively-invisible value; unlike the old components.html, 0 isn't accepted here.
)
