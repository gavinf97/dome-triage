"""Pure-Python curation session state -- no Streamlit/ipywidgets import, so it's unit-testable
without a browser (see tests/test_curate_state.py).

Resume behavior follows DOME_Top_Curate/curation.ipynb's proven pattern: "already decided" is
determined by presence in the event log and filtered out of the queue on load, rather than an
index checkpoint -- so a crashed session loses at most the one in-flight decision. The single
rolling backup-before-write (`backup_file`) also mirrors that notebook's `backup_file()` exactly.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import pandas as pd

from dome_triage.curate.bulk_scores import annotate_bulk_scores, annotate_screening
from dome_triage.sampling.stratified import build_strata

EVENT_COLUMNS = ["record_id", "decision", "tag", "notes", "features", "curator", "timestamp"]


def backup_file(path: Path) -> None:
    """Single rolling backup (overwrites any previous backup), matching curation.ipynb's
    backup_file(): copy the existing file aside before every write."""
    if path.exists():
        backup_path = path.with_name(f"{path.stem}_backup{path.suffix}")
        shutil.copy2(path, backup_path)


# A record already trusted at this confidence tier (from a prior curation round outside this
# session -- DOME_Top_Curate, the DOME registry API, etc.) is settled ground truth, not something
# that needs a fresh decision -- mirrors materialize_events' own "contradicts_trusted_prior" tier
# pairing below.
_TRUSTED_LABEL_CONFIDENCE = ("human_curated", "registry_confirmed")


@dataclass
class CurationSession:
    dataset_path: Path
    events_path: Path
    curator: str = "unknown"
    include_already_labeled: bool = False
    require_pmcid: bool = False

    # Optional lookups (see curate/bulk_scores.py) joining Step 12/14b's bulk-file-only columns
    # onto this session's rows for filtering/display -- canonical_dataset.csv itself never gains
    # these columns (see bulk_scores.py's module docstring for why). Built once by the caller
    # (streamlit_helpers.py caches them independently of these filter params) and passed in by
    # reference, so CurationSession never has to know how to read a 744k-row file.
    bulk_score_lookup: Optional[dict] = None
    screening_lookup: Optional[dict] = None

    # Filters -- each None/False means "no restriction", matching include_already_labeled/
    # require_pmcid's existing on/off-toggle pattern. score_band values are the integer band
    # labels build_strata() produces (0 = lowest quartile ... n_score_bands-1 = highest);
    # journals values are journal_bucket entries (an exact top-N journal name, or "other").
    score_band: Optional[list] = None
    journals: Optional[list] = None
    year_range: Optional[tuple] = None
    classification: Optional[list] = None
    needs_screening_only: bool = False
    n_score_bands: int = 4
    top_n_journals: int = 15

    dataset: pd.DataFrame = field(init=False, repr=False)
    events: pd.DataFrame = field(init=False, repr=False)
    queue: list = field(init=False, repr=False)
    _reviewable_ids: set = field(init=False, repr=False)
    _position: int = field(init=False, default=0)

    def __post_init__(self) -> None:
        self.dataset = pd.read_csv(self.dataset_path, dtype=str)
        self.events = (
            pd.read_csv(self.events_path, dtype=str)
            if Path(self.events_path).exists()
            else pd.DataFrame(columns=EVENT_COLUMNS)
        )
        decided = set(self.events["record_id"]) if not self.events.empty else set()

        reviewable = self.dataset
        if not self.include_already_labeled:
            trusted_mask = self.dataset["label_confidence"].isin(_TRUSTED_LABEL_CONFIDENCE) & self.dataset[
                "label"
            ].isin(["positive", "negative"])
            reviewable = reviewable[~trusted_mask]
        if self.require_pmcid:
            reviewable = reviewable[reviewable["pmcid"].notna() & (reviewable["pmcid"] != "")]

        if self.bulk_score_lookup:
            reviewable = annotate_bulk_scores(reviewable, self.bulk_score_lookup)
        if self.screening_lookup:
            reviewable = annotate_screening(reviewable, self.screening_lookup)

        if self.classification is not None:
            reviewable = reviewable[
                reviewable.get("bulk_match_classification", pd.Series(dtype=str)).isin(self.classification)
            ]
        if self.needs_screening_only:
            reviewable = reviewable[reviewable.get("needs_screening", pd.Series(dtype=bool)).fillna(False)]

        if self.journals is not None or self.score_band is not None:
            has_scores = "bulk_match_score" in reviewable.columns and reviewable["bulk_match_score"].notna().any()
            bucketed = build_strata(
                reviewable.assign(year=pd.to_numeric(reviewable["year"], errors="coerce")),
                score_col="bulk_match_score" if has_scores else None,
                n_score_bands=self.n_score_bands,
                top_n_journals=self.top_n_journals,
            )
            combined_mask = pd.Series(True, index=reviewable.index)
            if self.journals is not None:
                combined_mask &= bucketed["journal_bucket"].isin(self.journals)
            band_col = "match_score_band__bulk_match_score"
            if self.score_band is not None:
                combined_mask &= bucketed[band_col].isin(self.score_band) if band_col in bucketed.columns else False
            reviewable = reviewable[combined_mask]

        if self.year_range is not None:
            year_numeric = pd.to_numeric(reviewable["year"], errors="coerce")
            lo, hi = self.year_range
            reviewable = reviewable[(year_numeric >= lo) & (year_numeric <= hi)]

        self._reviewable_ids = set(reviewable["record_id"])
        self.queue = [
            rid for rid in self.dataset["record_id"] if rid in self._reviewable_ids and rid not in decided
        ]
        self._position = 0

    def diversity_stats(self) -> dict:
        """All-time/corpus-wide diversity of *confirmed* (trusted-source OR actually decided in
        this session's events, even before `curate materialize` runs) positive/negative
        decisions -- deliberately NOT scoped to whichever filter is currently active (matches
        term_review_state.py's all_time_counts(): a decision's diversity contribution doesn't
        depend on which lens you were viewing it through when you made it). Overlays this
        session's in-memory events on top of self.dataset (replicating materialize_events()'s
        "last event wins" logic transiently) so today's decisions move the numbers immediately,
        not only after a separate materialize step. Excludes not-yet-reviewed
        heuristic_candidate/unscored rows from "confirmed" -- otherwise merging a large unreviewed
        clear-negative batch (Step 14) would inflate coverage before a human looked at any of it."""
        effective = self.dataset[["record_id", "journal", "year", "label", "label_confidence"]].copy()
        reviewed_ids: set = set()
        if not self.events.empty:
            latest = self.events.sort_values("timestamp").groupby("record_id").last()
            reviewed_ids = set(latest.index)
            effective = effective.set_index("record_id")
            common = latest.index.intersection(effective.index)
            effective.loc[common, "label"] = latest.loc[common, "decision"]
            effective = effective.reset_index()

        confirmed_mask = effective["label_confidence"].isin(_TRUSTED_LABEL_CONFIDENCE) | effective[
            "record_id"
        ].isin(reviewed_ids)
        confirmed = effective[effective["label"].isin(["positive", "negative"]) & confirmed_mask]

        total_journals = self.dataset["journal"].nunique(dropna=True)
        covered_journals = confirmed["journal"].nunique(dropna=True)

        return {
            "journal_coverage_pct": (covered_journals / total_journals * 100) if total_journals else 0.0,
            "n_journals_covered": int(covered_journals),
            "n_journals_total": int(total_journals),
            "per_journal_counts": confirmed.groupby(["journal", "label"]).size().unstack(fill_value=0),
            "per_year_counts": confirmed.groupby(["year", "label"]).size().unstack(fill_value=0),
        }

    def total(self) -> int:
        return len(self._reviewable_ids)

    def remaining(self) -> int:
        return len(self.queue) - self._position

    def stats(self) -> dict:
        total = self.total()
        remaining = self.remaining()
        return {"total": total, "decided": total - remaining, "remaining": remaining}

    def current_record(self) -> Optional[pd.Series]:
        if self._position >= len(self.queue):
            return None
        record_id = self.queue[self._position]
        matches = self.dataset.loc[self.dataset["record_id"] == record_id]
        return matches.iloc[0] if not matches.empty else None

    def record_decision(
        self,
        decision: str,
        tag: Optional[str] = None,
        notes: str = "",
        features: Optional[dict] = None,
    ) -> None:
        """Appends one row to the event log (backup-before-write) and advances the queue.
        `decision` should be one of "positive"/"negative"/"undeterminable"/"skipped". `features`
        holds the structured curation-feature flags (configs/curation_features.yaml) as a dict,
        stored as JSON -- a living, extensible checklist, not a fixed schema."""
        record = self.current_record()
        if record is None:
            return

        row = {
            "record_id": record["record_id"],
            "decision": decision,
            "tag": tag or "",
            "notes": notes,
            "features": json.dumps(features) if features else "",
            "curator": self.curator,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        events_path = Path(self.events_path)
        backup_file(events_path)
        events_path.parent.mkdir(parents=True, exist_ok=True)
        header_needed = not events_path.exists()
        pd.DataFrame([row]).to_csv(events_path, mode="a", header=header_needed, index=False)

        self.events = pd.concat([self.events, pd.DataFrame([row])], ignore_index=True)
        self._position += 1


def materialize_events(dataset_path: Path, events_path: Path, output_path: Path) -> pd.DataFrame:
    """Folds curation_events.csv into the canonical dataset (last decision per record_id wins),
    flagging -- never silently overwriting -- any contradiction with a prior human_curated or
    registry_confirmed label. See AGENTS.md's "human curation is never bypassed" rule.

    A decision that lands cleanly (no conflict) also upgrades that row's `label_confidence` to
    `human_curated` -- a decision recorded through the Curate app is a real human judgment, on par
    with any other human_curated source, not a lesser tier. Before this, a record that started as
    e.g. `heuristic_candidate` (a bulk-match/clear-negative candidate) stayed at that confidence
    forever even after a human reviewed it via the app, making `label_confidence` alone unable to
    answer "was this actually reviewed" -- this fixes that. Conflicted rows keep their prior
    confidence untouched (it's already trusted-tier by definition -- that's what made it a
    conflict in the first place; there's nothing to upgrade)."""
    dataset = pd.read_csv(dataset_path, dtype=str)
    events_path = Path(events_path)
    if not events_path.exists():
        return dataset

    events = pd.read_csv(events_path, dtype=str)
    if events.empty:
        return dataset

    latest = events.sort_values("timestamp").groupby("record_id").last()

    for record_id, event in latest.iterrows():
        mask = dataset["record_id"] == record_id
        if not mask.any():
            continue

        prior_label = dataset.loc[mask, "label"].iloc[0]
        prior_confidence = dataset.loc[mask, "label_confidence"].iloc[0]
        new_label = event["decision"]

        contradicts_trusted_prior = (
            prior_confidence in ("human_curated", "registry_confirmed")
            and prior_label in ("positive", "negative")
            and new_label in ("positive", "negative", "undeterminable")
            and new_label != prior_label
        )

        dataset.loc[mask, "label"] = "conflict" if contradicts_trusted_prior else new_label
        dataset.loc[mask, "has_conflict"] = str(contradicts_trusted_prior)
        if not contradicts_trusted_prior:
            dataset.loc[mask, "label_confidence"] = "human_curated"
        dataset.loc[mask, "curation_tag"] = event.get("tag") or None
        dataset.loc[mask, "notes"] = event.get("notes") or None
        if event.get("features"):
            dataset.loc[mask, "curation_features"] = event["features"]
        dataset.loc[mask, "updated_at"] = datetime.now(timezone.utc).isoformat()

    output_path = Path(output_path)
    backup_file(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    dataset.to_csv(output_path, index=False)
    return dataset
