from dome_triage.ingest.epmc_client import EpmcClient


class _FakeResponse:
    def __init__(self, json_data: dict):
        self._json_data = json_data

    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict:
        return self._json_data


def test_count_returns_hit_count_from_a_single_request(monkeypatch):
    client = EpmcClient()
    captured_params = {}

    def fake_get(url, params=None, timeout=None):
        captured_params.update(params)
        return _FakeResponse({"hitCount": 42})

    monkeypatch.setattr(client.session, "get", fake_get)

    result = client.count('"machine learning"')

    assert result == 42
    assert captured_params["query"] == '"machine learning"'
    assert captured_params["pageSize"] == 1
    assert captured_params["resultType"] == "idlist"


def test_count_defaults_to_zero_when_hit_count_missing(monkeypatch):
    client = EpmcClient()
    monkeypatch.setattr(client.session, "get", lambda url, params=None, timeout=None: _FakeResponse({}))

    assert client.count('"anything"') == 0
