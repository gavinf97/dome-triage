"""Bulk blunt-match candidate construction: queries ALL of Europe PMC for
`"artificial intelligence"` OR `"machine learning"` (one combined, deduplicated query -- the
search API itself returns each unique record once even if it matches both phrases), one year at
a time, capturing full metadata (title/abstract/authors/journal/year/DOI/PMID/PMCID/MeSH/pub
types/open-access/author keywords) in one pass -- no separate enrichment needed for this source.

Deliberately chunked per-year rather than one multi-decade call: gives natural human-scale
checkpoints (run 2024, inspect, decide on 2023) per AGENTS.md's human-led execution rule. Within
a single year, an interrupted fetch is NOT resumed mid-year (only completed years are skipped on
rerun, via the `.done` marker) -- documented honestly rather than promising cursor-level restart
this doesn't implement.
"""

from __future__ import annotations

import json
from pathlib import Path

from dome_triage.ingest.epmc_client import EpmcClient
from dome_triage.ingest.id_mapping import clean_doi, clean_pmcid, clean_pmid
from dome_triage.ontology.mesh import extract_mesh_headings
from dome_triage.schema import RawRecord

AI_ML_QUERY = '"artificial intelligence" OR "machine learning"'


def _year_query(year: int) -> str:
    return f"({AI_ML_QUERY}) AND (FIRST_PDATE:[{year}-01-01 TO {year}-12-31])"


def fetch_ai_ml_candidates(client: EpmcClient, year: int, checkpoint_dir: Path) -> Path:
    """Fetches every AI/ML-matching record for `year` (resultType=core) into
    checkpoint_dir/bulk_match_<year>.jsonl. If that year was already completed (a
    `.done` marker exists), skips the fetch entirely and returns the existing path."""
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    output_path = checkpoint_dir / f"bulk_match_{year}.jsonl"
    done_marker = checkpoint_dir / f"bulk_match_{year}.done"

    if done_marker.exists():
        return output_path

    query = _year_query(year)
    with open(output_path, "w") as f:
        for result in client.search(query, result_type="core", show_progress=True):
            f.write(json.dumps(result) + "\n")

    done_marker.write_text("complete\n")
    return output_path


def core_result_to_raw_record(
    result: dict,
    source_name: str,
    source_file: str,
    label: str = "unlabeled",
    label_confidence: str = "unscored",
) -> RawRecord:
    pub_year = result.get("pubYear")
    year = int(pub_year) if pub_year and str(pub_year).isdigit() else None
    is_open_access = result.get("isOpenAccess")

    return RawRecord(
        source_name=source_name,
        source_file=source_file,
        label=label,
        label_confidence=label_confidence,
        pmcid=clean_pmcid(result.get("pmcid")),
        pmid=clean_pmid(result.get("pmid")),
        doi=clean_doi(result.get("doi")),
        title=result.get("title") or None,
        abstract=result.get("abstractText") or None,
        journal=(result.get("journalInfo", {}) or {}).get("journal", {}).get("title"),
        authors=result.get("authorString") or None,
        year=year,
        mesh_headings=extract_mesh_headings(result),
        pub_types=(result.get("pubTypeList") or {}).get("pubType") or [],
        is_open_access=(is_open_access == "Y") if is_open_access in ("Y", "N") else None,
        keywords_author=(result.get("keywordList") or {}).get("keyword") or [],
        fulltext_available=bool(result.get("inEPMC") == "Y" or result.get("inPMC") == "Y"),
    )


def load_bulk_match_year(jsonl_path: Path, year: int) -> list[RawRecord]:
    """Loads a fetched per-year JSONL cache into RawRecords."""
    source_name = f"bulk_match_{year}"
    records = []
    with open(jsonl_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            result = json.loads(line)
            records.append(core_result_to_raw_record(result, source_name, str(jsonl_path)))
    return records
