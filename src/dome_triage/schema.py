"""Canonical record schema for the consolidated labeled dataset (Phase 1 output).

See ROADMAP.md Phase 1 and AGENTS.md's provenance section before changing these fields --
`sources` is the audit trail that lets a human trace any label back to the file it came from.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict

Label = Literal["positive", "negative", "skipped", "conflict", "unlabeled"]
LabelConfidence = Literal["human_curated", "registry_confirmed", "heuristic_candidate"]
CurationTag = Literal["uncertain", "close_negative"]


class SourceProvenance(BaseModel):
    model_config = ConfigDict(frozen=True)

    source_name: str
    source_label: Label
    source_label_confidence: LabelConfidence
    source_file: str
    matched_on: Optional[str] = None  # which normalized ID field this row shared with the cluster


class CanonicalRecord(BaseModel):
    """One row of data/processed/canonical_dataset.csv."""

    record_id: str
    canonical_key: str

    pmcid: Optional[str] = None
    pmid: Optional[str] = None
    doi: Optional[str] = None

    title: Optional[str] = None
    abstract: Optional[str] = None
    journal: Optional[str] = None
    authors: Optional[str] = None
    year: Optional[int] = None
    citation_count: Optional[int] = None

    label: Label = "unlabeled"
    label_confidence: Optional[LabelConfidence] = None

    sources: list[SourceProvenance] = []
    source_count: int = 0
    has_conflict: bool = False

    match_metadata: Optional[dict] = None

    fulltext_available: bool = False
    fulltext_manifest_ref: Optional[str] = None

    curation_tag: Optional[CurationTag] = None
    notes: Optional[str] = None

    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class RawRecord(BaseModel):
    """One row loaded from a source file before dedup/consolidation, i.e. data/interim/raw_records*.csv."""

    source_name: str
    source_file: str
    label: Label
    label_confidence: LabelConfidence

    pmcid: Optional[str] = None
    pmid: Optional[str] = None
    doi: Optional[str] = None

    title: Optional[str] = None
    abstract: Optional[str] = None
    journal: Optional[str] = None
    authors: Optional[str] = None
    year: Optional[int] = None
    citation_count: Optional[int] = None

    match_metadata: Optional[dict] = None
    fulltext_available: bool = False
    fulltext_source_root: Optional[str] = None
