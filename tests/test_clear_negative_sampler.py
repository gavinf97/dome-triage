from dome_triage.ingest.clear_negative_sampler import fetch_clear_negatives


def _fake_result(idx: int, journal: str, year: int) -> dict:
    return {
        "pmid": str(1000 + idx),
        "pmcid": None,
        "doi": None,
        "title": f"Paper {idx}",
        "abstractText": "An abstract with no AI/ML mention.",
        "authorString": "Someone A.",
        "journalInfo": {"journal": {"title": journal}},
        "pubYear": str(year),
        "isOpenAccess": "N",
        "pubTypeList": {"pubType": ["research-article"]},
        "keywordList": {"keyword": []},
        "inEPMC": "N",
        "meshHeadingList": {"meshHeading": []},
    }


class _FakeSearchClient:
    """Mirrors EpmcClient.search()'s signature -- returns the same fixed batch for every call,
    matching this project's existing test pattern (_FakeCountClient in test_bulk_match.py)."""

    def __init__(self, results: list[dict]):
        self.results = results
        self.queries_seen: list[str] = []

    def search(self, query, result_type="core", page_size=None, show_progress=False):
        self.queries_seen.append(query)
        return list(self.results)


def _diverse_results(n_per_journal: int = 5) -> list[dict]:
    journals_years = [
        ("Journal A", 2010),
        ("Journal B", 2015),
        ("Journal C", 2020),
        ("Journal D", 2005),
    ]
    results = []
    idx = 0
    for journal, year in journals_years:
        for _ in range(n_per_journal):
            results.append(_fake_result(idx, journal, year))
            idx += 1
    return results


def test_fetch_clear_negatives_returns_raw_pool_when_below_sample_size():
    client = _FakeSearchClient(_diverse_results(n_per_journal=2))  # 8 raw records
    df = fetch_clear_negatives(client, 2000, 2020, sample_size=100, n_windows=1)

    assert len(df) == 8
    assert "journal_bucket" not in df.columns
    assert "year_bucket" not in df.columns
    assert set(df["label"]) == {"negative"}
    assert set(df["label_confidence"]) == {"heuristic_candidate"}
    assert set(df["source_name"]) == {"clear_negative_sampler"}


def test_fetch_clear_negatives_stratifies_and_caps_when_above_sample_size():
    client = _FakeSearchClient(_diverse_results(n_per_journal=10))  # 40 raw records, 4 journals

    df = fetch_clear_negatives(client, 2000, 2020, sample_size=12, n_windows=1, top_n_journals=4)

    assert len(df) <= 12
    assert "journal_bucket" not in df.columns  # strata columns never leak into the return value
    # stratification must actually spread across journals, not just take the first 12 raw rows
    # (which would all be "Journal A" given _diverse_results' construction order).
    assert df["journal"].nunique() > 1


def test_fetch_clear_negatives_calls_search_once_per_window():
    client = _FakeSearchClient(_diverse_results(n_per_journal=1))
    fetch_clear_negatives(client, 2000, 2001, sample_size=100, n_windows=3)

    assert len(client.queries_seen) == 3
    for query in client.queries_seen:
        assert "NOT" in query
        assert "artificial intelligence" in query
