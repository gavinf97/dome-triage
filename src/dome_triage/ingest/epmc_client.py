"""Europe PMC REST API client.

Ported from DOME-Copilot-Data-Analysis/EPMC_growth_graph/fetch_epmc_growth_data.py, which already
proved out the cursorMark deep-pagination + urllib3 Retry pattern against this exact API. Extended
here with a batch metadata lookup (`get_by_ids`) used by `ingest enrich-metadata` to fill in
title/abstract for the id_pair_only and pdf_directory_gold source rows, which only carry IDs.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Literal, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

DEFAULT_BASE_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest"
_BATCH_CHUNK_SIZE = 40  # keep query URLs well under length limits


def create_session(max_retries: int = 5, backoff_factor: float = 1.0) -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=max_retries,
        backoff_factor=backoff_factor,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=10, pool_maxsize=20)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


class EpmcClient:
    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        page_size: int = 100,
        max_retries: int = 5,
        backoff_factor: float = 1.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.page_size = page_size
        self.session = create_session(max_retries, backoff_factor)

    def search(
        self, query: str, result_type: str = "core", page_size: Optional[int] = None
    ) -> Iterator[dict]:
        """Yield every result for `query` via cursorMark deep pagination."""
        cursor = "*"
        page_size = page_size or self.page_size
        while True:
            params = {
                "query": query,
                "pageSize": page_size,
                "cursorMark": cursor,
                "format": "json",
                "resultType": result_type,
            }
            resp = self.session.get(f"{self.base_url}/search", params=params, timeout=60)
            resp.raise_for_status()
            data = resp.json()

            results = data.get("resultList", {}).get("result", [])
            if not results:
                return
            yield from results

            next_cursor = data.get("nextCursorMark", "")
            if not next_cursor or next_cursor == cursor:
                return
            cursor = next_cursor

    def get_by_ids(
        self, ids: list[str], id_type: Literal["pmcid", "pmid", "doi"]
    ) -> dict[str, dict]:
        """Batch metadata lookup. Returns {id: result_dict} for whichever ids were found;
        missing ids are simply absent from the returned dict (never raises for a partial miss)."""
        field = {"pmcid": "PMCID", "pmid": "EXT_ID", "doi": "DOI"}[id_type]
        found: dict[str, dict] = {}
        for i in range(0, len(ids), _BATCH_CHUNK_SIZE):
            chunk = ids[i : i + _BATCH_CHUNK_SIZE]
            clauses = " OR ".join(f'{field}:"{value}"' for value in chunk)
            query = clauses if id_type != "pmid" else f"({clauses}) AND SRC:MED"
            for result in self.search(query, result_type="core", page_size=len(chunk)):
                key = self._extract_key(result, id_type)
                if key:
                    found[key] = result
        return found

    @staticmethod
    def _extract_key(result: dict, id_type: Literal["pmcid", "pmid", "doi"]) -> Optional[str]:
        if id_type == "pmcid":
            return result.get("pmcid")
        if id_type == "pmid":
            return result.get("pmid")
        return result.get("doi")

    def close(self) -> None:
        self.session.close()
