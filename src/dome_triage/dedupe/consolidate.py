"""Merges each cluster (dedupe/keys.py) into one CanonicalRecord with full provenance, applying
conflict detection (dedupe/conflicts.py) rather than silently resolving disagreements.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Optional, TypeVar

import pandas as pd

from dome_triage.dedupe.conflicts import merge_label
from dome_triage.dedupe.keys import ID_FIELDS, build_clusters, choose_canonical_key
from dome_triage.schema import CanonicalRecord, RawRecord, SourceProvenance

T = TypeVar("T")


def _matched_on(record: RawRecord) -> str:
    return ",".join(field for field in ID_FIELDS if getattr(record, field))


def _pick_longest(values: list[Optional[str]]) -> Optional[str]:
    candidates = [v for v in values if v]
    return max(candidates, key=len) if candidates else None


def _pick_first(values: list[Optional[T]]) -> Optional[T]:
    return next((v for v in values if v is not None), None)


def _merge_cluster(cluster: list[RawRecord], id_priority: tuple[str, ...]) -> CanonicalRecord:
    canonical_key = choose_canonical_key(cluster, id_priority)
    record_id = hashlib.sha1(canonical_key.encode()).hexdigest()

    label, label_confidence = merge_label(cluster)
    now = datetime.now(timezone.utc).isoformat()

    sources = [
        SourceProvenance(
            source_name=r.source_name,
            source_label=r.label,
            source_label_confidence=r.label_confidence,
            source_file=r.source_file,
            matched_on=_matched_on(r),
        )
        for r in cluster
    ]

    return CanonicalRecord(
        record_id=record_id,
        canonical_key=canonical_key,
        pmcid=_pick_first([r.pmcid for r in cluster]),
        pmid=_pick_first([r.pmid for r in cluster]),
        doi=_pick_first([r.doi for r in cluster]),
        title=_pick_longest([r.title for r in cluster]),
        abstract=_pick_longest([r.abstract for r in cluster]),
        journal=_pick_first([r.journal for r in cluster]),
        authors=_pick_first([r.authors for r in cluster]),
        year=_pick_first([r.year for r in cluster]),
        citation_count=_pick_first([r.citation_count for r in cluster]),
        label=label,
        label_confidence=label_confidence,
        sources=sources,
        source_count=len(cluster),
        has_conflict=(label == "conflict"),
        match_metadata=_pick_first([r.match_metadata for r in cluster]),
        fulltext_available=any(r.fulltext_available for r in cluster),
        created_at=now,
        updated_at=now,
    )


def consolidate(
    records: list[RawRecord], id_priority: tuple[str, ...] = ("pmcid", "doi", "pmid")
) -> list[CanonicalRecord]:
    clusters = build_clusters(records)
    return [_merge_cluster(cluster, id_priority) for cluster in clusters]


def to_dataframe(canonical_records: list[CanonicalRecord]) -> pd.DataFrame:
    rows = []
    for rec in canonical_records:
        row = rec.model_dump()
        row["sources"] = json.dumps(row["sources"])
        if row.get("match_metadata"):
            row["match_metadata"] = json.dumps(row["match_metadata"])
        rows.append(row)
    return pd.DataFrame(rows)


def conflicts_dataframe(canonical_records: list[CanonicalRecord]) -> pd.DataFrame:
    """One row per contributing source for every conflicting cluster -- for the curation app's
    Conflicts page. Every contributing row is preserved; none are dropped or auto-resolved."""
    rows = []
    for rec in canonical_records:
        if not rec.has_conflict:
            continue
        for src in rec.sources:
            rows.append(
                {
                    "record_id": rec.record_id,
                    "canonical_key": rec.canonical_key,
                    "title": rec.title,
                    "abstract": rec.abstract,
                    "source_name": src.source_name,
                    "source_label": src.source_label,
                    "source_label_confidence": src.source_label_confidence,
                    "source_file": src.source_file,
                    "matched_on": src.matched_on,
                }
            )
    return pd.DataFrame(rows)
