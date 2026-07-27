import pandas as pd

from dome_triage.curate.state import CurationSession


def _write_dataset(path):
    df = pd.DataFrame(
        {
            "record_id": ["rec1", "rec2", "rec3"],
            "title": ["Paper One", "Paper Two", "Paper Three"],
            "abstract": ["Abstract one.", "Abstract two.", "Abstract three."],
            "journal": ["J1", "J2", "J3"],
            "year": ["2020", "2021", "2022"],
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
