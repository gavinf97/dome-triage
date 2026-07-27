from dome_triage.dedupe.keys import build_clusters, choose_canonical_key
from dome_triage.schema import RawRecord


def _record(**kwargs) -> RawRecord:
    defaults = {
        "source_name": "test",
        "source_file": "test.csv",
        "label": "positive",
        "label_confidence": "human_curated",
    }
    defaults.update(kwargs)
    return RawRecord(**defaults)


def test_records_sharing_only_a_doi_are_merged():
    # Record A has no DOI overlap partner via PMCID/PMID -- only the DOI connects them.
    a = _record(doi="10.1000/shared", pmcid="PMC1000001")
    b = _record(doi="10.1000/shared", pmid="22222222")

    clusters = build_clusters([a, b])

    assert len(clusters) == 1
    assert len(clusters[0]) == 2
    assert a in clusters[0] and b in clusters[0]


def test_records_with_different_pmcids_are_not_merged_even_if_similar():
    a = _record(pmcid="PMC1000001", title="A machine learning paper")
    b = _record(pmcid="PMC1000002", title="A machine learning paper")  # similar title, no fuzzy match

    clusters = build_clusters([a, b])

    assert len(clusters) == 2


def test_transitive_merge_across_three_sources_via_different_shared_ids():
    # A-B share a PMCID; B-C share a PMID; no direct ID in common between A and C.
    a = _record(pmcid="PMC9999999", doi="10.1000/a")
    b = _record(pmcid="PMC9999999", pmid="33333333")
    c = _record(pmid="33333333", doi="10.1000/c")

    clusters = build_clusters([a, b, c])

    assert len(clusters) == 1
    assert len(clusters[0]) == 3
    assert a in clusters[0] and b in clusters[0] and c in clusters[0]


def test_choose_canonical_key_respects_priority_order():
    cluster = [
        _record(pmid="12345678"),
        _record(doi="10.1000/x", pmid="12345678"),
        _record(pmcid="PMC1234567", doi="10.1000/x", pmid="12345678"),
    ]

    assert choose_canonical_key(cluster, ("pmcid", "doi", "pmid")) == "PMCID:PMC1234567"
    assert choose_canonical_key(cluster, ("doi", "pmcid", "pmid")) == "DOI:10.1000/x"
