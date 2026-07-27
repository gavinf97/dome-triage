"""Pure-Python curation session state -- no Streamlit/ipywidgets import, so it's unit-testable
without a browser (see tests/test_curate_state.py).

Resume behavior follows DOME_Top_Curate/curation.ipynb's proven pattern: "already decided" is
determined by presence in the event log and filtered out of the queue on load, rather than an
index checkpoint -- so a crashed session loses at most the one in-flight decision. The single
rolling backup-before-write (`backup_file`) also mirrors that notebook's `backup_file()` exactly.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import pandas as pd

EVENT_COLUMNS = ["record_id", "decision", "tag", "notes", "curator", "timestamp"]


def backup_file(path: Path) -> None:
    """Single rolling backup (overwrites any previous backup), matching curation.ipynb's
    backup_file(): copy the existing file aside before every write."""
    if path.exists():
        backup_path = path.with_name(f"{path.stem}_backup{path.suffix}")
        shutil.copy2(path, backup_path)


@dataclass
class CurationSession:
    dataset_path: Path
    events_path: Path
    curator: str = "unknown"

    dataset: pd.DataFrame = field(init=False, repr=False)
    events: pd.DataFrame = field(init=False, repr=False)
    queue: list = field(init=False, repr=False)
    _position: int = field(init=False, default=0)

    def __post_init__(self) -> None:
        self.dataset = pd.read_csv(self.dataset_path, dtype=str)
        self.events = (
            pd.read_csv(self.events_path, dtype=str)
            if Path(self.events_path).exists()
            else pd.DataFrame(columns=EVENT_COLUMNS)
        )
        decided = set(self.events["record_id"]) if not self.events.empty else set()
        self.queue = [rid for rid in self.dataset["record_id"] if rid not in decided]
        self._position = 0

    def total(self) -> int:
        return len(self.dataset)

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

    def record_decision(self, decision: str, tag: Optional[str] = None, notes: str = "") -> None:
        """Appends one row to the event log (backup-before-write) and advances the queue.
        `decision` should be one of "positive"/"negative"/"skipped"."""
        record = self.current_record()
        if record is None:
            return

        row = {
            "record_id": record["record_id"],
            "decision": decision,
            "tag": tag or "",
            "notes": notes,
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
    registry_confirmed label. See AGENTS.md's "human curation is never bypassed" rule."""
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
            and new_label in ("positive", "negative")
            and new_label != prior_label
        )

        dataset.loc[mask, "label"] = "conflict" if contradicts_trusted_prior else new_label
        dataset.loc[mask, "has_conflict"] = contradicts_trusted_prior
        dataset.loc[mask, "curation_tag"] = event.get("tag") or None
        dataset.loc[mask, "notes"] = event.get("notes") or None
        dataset.loc[mask, "updated_at"] = datetime.now(timezone.utc).isoformat()

    output_path = Path(output_path)
    backup_file(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    dataset.to_csv(output_path, index=False)
    return dataset
