"""Fills in title/abstract/journal/year/authors for records that only carry IDs (the id_pair_only
and pdf_directory_gold adapters, and any dome_registry_api_json rows missing a PMCID) via a
batched Europe PMC lookup, with an NCBI ID Converter fallback to derive a PMCID from a DOI first.
"""

from __future__ import annotations

from dome_triage.ingest.epmc_client import EpmcClient
from dome_triage.ingest.id_mapping import clean_pmcid, doi_to_pmcid
from dome_triage.schema import RawRecord


def _needs_enrichment(record: RawRecord) -> bool:
    return not record.title or not record.abstract


def enrich_missing_metadata(records: list[RawRecord], client: EpmcClient) -> list[RawRecord]:
    to_enrich = [r for r in records if _needs_enrichment(r)]
    if not to_enrich:
        return records

    for record in to_enrich:
        if not record.pmcid and record.doi:
            record.pmcid = doi_to_pmcid(record.doi)

    by_pmcid = {r.pmcid: r for r in to_enrich if r.pmcid}
    by_pmid = {r.pmid: r for r in to_enrich if not r.pmcid and r.pmid}

    if by_pmcid:
        found = client.get_by_ids(list(by_pmcid.keys()), id_type="pmcid")
        for pmcid, result in found.items():
            _apply_epmc_result(by_pmcid[pmcid], result)

    if by_pmid:
        found = client.get_by_ids(list(by_pmid.keys()), id_type="pmid")
        for pmid, result in found.items():
            _apply_epmc_result(by_pmid[pmid], result)

    return records


def _apply_epmc_result(record: RawRecord, result: dict) -> None:
    record.title = record.title or result.get("title")
    record.abstract = record.abstract or result.get("abstractText")
    journal_info = result.get("journalInfo") or {}
    record.journal = record.journal or (journal_info.get("journal") or {}).get("title")
    record.authors = record.authors or result.get("authorString")
    record.doi = record.doi or result.get("doi")
    record.pmcid = record.pmcid or clean_pmcid(result.get("pmcid"))
    if not record.year and result.get("pubYear"):
        try:
            record.year = int(result["pubYear"])
        except (TypeError, ValueError):
            pass
