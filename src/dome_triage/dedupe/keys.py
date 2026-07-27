"""Union-find clustering: two RawRecords merge into the same cluster if they share ANY normalized
ID (pmcid, doi, or pmid) between them -- not just a single priority field. This matters because
Adapter B rows (configs/sources.yaml `id_pair_only`) carry no DOI, so matching only on "the first
non-null field in priority order" would miss real duplicates that share a DOI or PMID with a row
from another source. The configured `dedup.id_priority` in sources.yaml is used only to choose the
*displayed* canonical_key for an already-formed cluster (see choose_canonical_key below), never to
decide cluster membership.
"""

from __future__ import annotations

from dome_triage.schema import RawRecord

ID_FIELDS = ("pmcid", "doi", "pmid")
_KEY_PREFIX = {"pmcid": "PMCID", "doi": "DOI", "pmid": "PMID"}


class UnionFind:
    def __init__(self) -> None:
        self._parent: dict[str, str] = {}

    def find(self, x: str) -> str:
        self._parent.setdefault(x, x)
        while self._parent[x] != x:
            self._parent[x] = self._parent[self._parent[x]]  # path halving
            x = self._parent[x]
        return x

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self._parent[ra] = rb


def _record_ids(record: RawRecord) -> list[str]:
    return [
        f"{field}:{value}"
        for field in ID_FIELDS
        if (value := getattr(record, field))
    ]


def build_clusters(records: list[RawRecord]) -> list[list[RawRecord]]:
    """Group records sharing any normalized ID into clusters. Records with no usable ID
    (shouldn't occur here -- source_loaders routes ID-less rows to `unresolved` instead) each
    become their own singleton cluster so no data is silently dropped."""
    uf = UnionFind()
    for record in records:
        ids = _record_ids(record)
        first, rest = (ids[0], ids[1:]) if ids else (None, [])
        for other_id in rest:
            uf.union(first, other_id)

    clusters_by_root: dict[str, list[RawRecord]] = {}
    standalone: list[list[RawRecord]] = []
    for record in records:
        ids = _record_ids(record)
        if not ids:
            standalone.append([record])
            continue
        root = uf.find(ids[0])
        clusters_by_root.setdefault(root, []).append(record)

    return list(clusters_by_root.values()) + standalone


def choose_canonical_key(
    cluster: list[RawRecord], priority: tuple[str, ...] = ("pmcid", "doi", "pmid")
) -> str:
    """Pick the displayed key for an already-formed cluster, using the configured priority order."""
    for field in priority:
        for record in cluster:
            value = getattr(record, field)
            if value:
                return f"{_KEY_PREFIX[field]}:{value}"
    raise ValueError("Cluster has no usable ID on any contributing record")
