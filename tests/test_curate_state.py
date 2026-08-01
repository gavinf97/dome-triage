import json

import pandas as pd

from dome_triage.curate.state import CurationSession, materialize_events


def _write_dataset(path):
    # label/label_confidence/pmcid default to neutral values (unlabeled/unscored/no pmcid) so
    # none of them trip the include_already_labeled/require_pmcid filters below -- existing tests
    # that don't care about those toggles see the same 3-record queue as before.
    df = pd.DataFrame(
        {
            "record_id": ["rec1", "rec2", "rec3"],
            "title": ["Paper One", "Paper Two", "Paper Three"],
            "abstract": ["Abstract one.", "Abstract two.", "Abstract three."],
            "journal": ["J1", "J2", "J3"],
            "year": ["2020", "2021", "2022"],
            "label": ["unlabeled", "unlabeled", "unlabeled"],
            "label_confidence": ["unscored", "unscored", "unscored"],
            "pmcid": ["", "", ""],
        }
    )
    df.to_csv(path, index=False)
    return path


def test_fresh_session_queues_all_records(tmp_path):
    dataset_path = _write_dataset(tmp_path / "canonical_dataset.csv")
    events_path = tmp_path / "curation_events.csv"

    session = CurationSession(dataset_path=dataset_path, events_path=events_path, curator="alice")

    assert session.stats() == {"total": 3, "decided": 0, "remaining": 3}
    assert session.current_record()["record_id"] == "rec1"


def test_record_decision_advances_queue_and_writes_event_log(tmp_path):
    dataset_path = _write_dataset(tmp_path / "canonical_dataset.csv")
    events_path = tmp_path / "curation_events.csv"
    session = CurationSession(dataset_path=dataset_path, events_path=events_path, curator="alice")

    session.record_decision("positive", tag=None, notes="looks good")

    assert events_path.exists()
    events = pd.read_csv(events_path)
    assert len(events) == 1
    assert events.iloc[0]["record_id"] == "rec1"
    assert events.iloc[0]["decision"] == "positive"
    assert session.current_record()["record_id"] == "rec2"
    assert session.stats() == {"total": 3, "decided": 1, "remaining": 2}


def test_backup_created_before_second_write(tmp_path):
    dataset_path = _write_dataset(tmp_path / "canonical_dataset.csv")
    events_path = tmp_path / "curation_events.csv"
    session = CurationSession(dataset_path=dataset_path, events_path=events_path, curator="alice")

    session.record_decision("positive")
    backup_path = tmp_path / "curation_events_backup.csv"
    assert not backup_path.exists()  # no prior file to back up on the first write

    session.record_decision("negative")
    assert backup_path.exists()  # second write backs up the file as it existed after the first


def test_resume_after_crash_skips_already_decided_records(tmp_path):
    dataset_path = _write_dataset(tmp_path / "canonical_dataset.csv")
    events_path = tmp_path / "curation_events.csv"

    first_session = CurationSession(
        dataset_path=dataset_path, events_path=events_path, curator="alice"
    )
    first_session.record_decision("positive")  # decides rec1, then session "crashes"

    resumed_session = CurationSession(
        dataset_path=dataset_path, events_path=events_path, curator="alice"
    )

    assert resumed_session.stats() == {"total": 3, "decided": 1, "remaining": 2}
    assert resumed_session.current_record()["record_id"] == "rec2"


def test_record_decision_stores_structured_features_as_json(tmp_path):
    dataset_path = _write_dataset(tmp_path / "canonical_dataset.csv")
    events_path = tmp_path / "curation_events.csv"
    session = CurationSession(dataset_path=dataset_path, events_path=events_path, curator="alice")

    session.record_decision(
        "positive", features={"applies_ml_to_data": True, "domain_area": "genomics"}
    )

    events = pd.read_csv(events_path)
    stored_features = json.loads(events.iloc[0]["features"])
    assert stored_features == {"applies_ml_to_data": True, "domain_area": "genomics"}


def test_record_decision_allows_undeterminable(tmp_path):
    # "undeterminable" must be accepted as a genuine decision value, not just tolerated.
    dataset_path = _write_dataset(tmp_path / "canonical_dataset.csv")
    events_path = tmp_path / "curation_events.csv"
    session = CurationSession(dataset_path=dataset_path, events_path=events_path, curator="alice")

    session.record_decision("undeterminable", notes="genuinely unclear even with abstract")

    events = pd.read_csv(events_path)
    assert events.iloc[0]["decision"] == "undeterminable"


def _write_dataset_with_mixed_trust(path):
    df = pd.DataFrame(
        {
            "record_id": ["rec1", "rec2", "rec3", "rec4"],
            "title": ["Trusted positive", "Trusted negative", "Heuristic positive", "Unlabeled"],
            "abstract": ["a", "b", "c", "d"],
            "journal": ["J1", "J2", "J3", "J4"],
            "year": ["2020", "2021", "2022", "2023"],
            "label": ["positive", "negative", "positive", "unlabeled"],
            "label_confidence": ["human_curated", "registry_confirmed", "heuristic_candidate", "unscored"],
            "pmcid": ["PMC1", "", "PMC3", ""],
        }
    )
    df.to_csv(path, index=False)
    return path


def test_trusted_prior_labeled_records_excluded_from_queue_by_default(tmp_path):
    # rec1 (human_curated) and rec2 (registry_confirmed) are already-settled ground truth from a
    # prior curation round -- they must NOT flood a fresh queue. rec3 (heuristic_candidate) and
    # rec4 (unlabeled) still need review.
    dataset_path = _write_dataset_with_mixed_trust(tmp_path / "canonical_dataset.csv")
    session = CurationSession(dataset_path=dataset_path, events_path=tmp_path / "events.csv", curator="alice")

    assert session.total() == 2
    ids_in_queue = set(session.queue)
    assert ids_in_queue == {"rec3", "rec4"}


def test_include_already_labeled_toggle_restores_full_queue(tmp_path):
    dataset_path = _write_dataset_with_mixed_trust(tmp_path / "canonical_dataset.csv")
    session = CurationSession(
        dataset_path=dataset_path,
        events_path=tmp_path / "events.csv",
        curator="alice",
        include_already_labeled=True,
    )

    assert session.total() == 4
    assert set(session.queue) == {"rec1", "rec2", "rec3", "rec4"}


def test_require_pmcid_filters_queue_to_records_with_a_pmcid(tmp_path):
    dataset_path = _write_dataset_with_mixed_trust(tmp_path / "canonical_dataset.csv")
    session = CurationSession(
        dataset_path=dataset_path,
        events_path=tmp_path / "events.csv",
        curator="alice",
        include_already_labeled=True,  # isolate the pmcid filter from the trust filter
        require_pmcid=True,
    )

    assert set(session.queue) == {"rec1", "rec3"}  # only these two have a pmcid


def _write_canonical_dataset_with_label(path, label="positive", label_confidence="human_curated"):
    df = pd.DataFrame(
        {
            "record_id": ["rec1"],
            "title": ["Paper One"],
            "abstract": ["Abstract one."],
            "label": [label],
            "label_confidence": [label_confidence],
            "has_conflict": [False],
            "curation_tag": [None],
            "notes": [None],
            "updated_at": [None],
        }
    )
    df.to_csv(path, index=False)
    return path


def test_materialize_events_applies_decision_when_no_conflict(tmp_path):
    dataset_path = _write_canonical_dataset_with_label(
        tmp_path / "canonical_dataset.csv", label="unlabeled", label_confidence="unscored"
    )
    events_path = tmp_path / "curation_events.csv"
    pd.DataFrame(
        [
            {
                "record_id": "rec1",
                "decision": "positive",
                "tag": "",
                "notes": "looks good",
                "features": json.dumps({"applies_ml_to_data": True}),
                "curator": "alice",
                "timestamp": "2026-01-01T00:00:00+00:00",
            }
        ]
    ).to_csv(events_path, index=False)

    output_path = tmp_path / "canonical_dataset.csv"
    result = materialize_events(dataset_path, events_path, output_path)

    assert result.loc[0, "label"] == "positive"
    assert result.loc[0, "has_conflict"] == "False"
    assert json.loads(result.loc[0, "curation_features"]) == {"applies_ml_to_data": True}


def test_materialize_events_flags_conflict_with_trusted_prior_label(tmp_path):
    # A record already trusted as human_curated positive must NOT be silently overwritten if a
    # new curation session decides negative -- this must surface as a conflict instead.
    dataset_path = _write_canonical_dataset_with_label(
        tmp_path / "canonical_dataset.csv", label="positive", label_confidence="human_curated"
    )
    events_path = tmp_path / "curation_events.csv"
    pd.DataFrame(
        [
            {
                "record_id": "rec1",
                "decision": "negative",
                "tag": "",
                "notes": "",
                "features": "",
                "curator": "alice",
                "timestamp": "2026-01-01T00:00:00+00:00",
            }
        ]
    ).to_csv(events_path, index=False)

    output_path = tmp_path / "canonical_dataset.csv"
    result = materialize_events(dataset_path, events_path, output_path)

    assert result.loc[0, "label"] == "conflict"
    assert result.loc[0, "has_conflict"] == "True"


def test_materialize_events_flags_conflict_when_undeterminable_contradicts_trusted_prior(tmp_path):
    dataset_path = _write_canonical_dataset_with_label(
        tmp_path / "canonical_dataset.csv", label="positive", label_confidence="registry_confirmed"
    )
    events_path = tmp_path / "curation_events.csv"
    pd.DataFrame(
        [
            {
                "record_id": "rec1",
                "decision": "undeterminable",
                "tag": "",
                "notes": "",
                "features": "",
                "curator": "alice",
                "timestamp": "2026-01-01T00:00:00+00:00",
            }
        ]
    ).to_csv(events_path, index=False)

    result = materialize_events(dataset_path, events_path, tmp_path / "canonical_dataset.csv")
    assert result.loc[0, "label"] == "conflict"
