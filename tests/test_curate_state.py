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
    assert result.loc[0, "label_confidence"] == "human_curated"
    assert json.loads(result.loc[0, "curation_features"]) == {"applies_ml_to_data": True}


def test_materialize_events_upgrades_heuristic_candidate_confidence_on_review(tmp_path):
    # The exact real-world case this exists for: a bulk-match/clear-negative candidate merged in
    # at heuristic_candidate confidence, then a human actually reviews it via the app -- that
    # review must count as a real human judgment, not stay stuck at the original heuristic tier.
    dataset_path = _write_canonical_dataset_with_label(
        tmp_path / "canonical_dataset.csv", label="negative", label_confidence="heuristic_candidate"
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

    result = materialize_events(dataset_path, events_path, tmp_path / "canonical_dataset.csv")

    assert result.loc[0, "label"] == "negative"
    assert result.loc[0, "label_confidence"] == "human_curated"


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
    # already trusted-tier -- that's what made it a conflict; nothing to upgrade, must stay put.
    assert result.loc[0, "label_confidence"] == "human_curated"


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


def _write_dataset_for_filters(path):
    df = pd.DataFrame(
        {
            "record_id": ["rec1", "rec2", "rec3", "rec4"],
            "title": ["P1", "P2", "P3", "P4"],
            "abstract": ["a", "b", "c", "d"],
            "journal": ["Nature", "Nature", "Science", "Obscure Journal"],
            "year": ["2018", "2022", "2020", "2015"],
            "label": ["unlabeled"] * 4,
            "label_confidence": ["unscored"] * 4,
            "pmcid": ["PMC1", "PMC2", "PMC3", "PMC4"],
            "pmid": ["", "", "", ""],
            "doi": ["", "", "", ""],
        }
    )
    df.to_csv(path, index=False)
    return path


_FILTER_SCORE_LOOKUP = {
    "PMC1": (10.0, "negative"),
    "PMC2": (200.0, "positive"),
    "PMC3": (150.0, "positive"),
    "PMC4": (5.0, "negative"),
}
_FILTER_SCREENING_LOOKUP = {"PMC1": True, "PMC2": False, "PMC3": False, "PMC4": False}


def test_classification_filter_restricts_queue(tmp_path):
    dataset_path = _write_dataset_for_filters(tmp_path / "canonical_dataset.csv")
    session = CurationSession(
        dataset_path=dataset_path,
        events_path=tmp_path / "events.csv",
        curator="alice",
        bulk_score_lookup=_FILTER_SCORE_LOOKUP,
        classification=["positive"],
    )
    assert set(session.queue) == {"rec2", "rec3"}


def test_year_range_filter_restricts_queue(tmp_path):
    dataset_path = _write_dataset_for_filters(tmp_path / "canonical_dataset.csv")
    session = CurationSession(
        dataset_path=dataset_path,
        events_path=tmp_path / "events.csv",
        curator="alice",
        year_range=(2019, 2022),
    )
    assert set(session.queue) == {"rec2", "rec3"}  # 2022 and 2020; 2018/2015 excluded


def test_journal_filter_matches_exact_journal_names(tmp_path):
    # journals filters directly against the real `journal` column (not a top-N-or-"other"
    # bucket) -- a curator searching for a specific journal by name needs an exact match, and
    # must be able to select ANY journal, not just one from a pre-baked top-N shortlist.
    dataset_path = _write_dataset_for_filters(tmp_path / "canonical_dataset.csv")
    session = CurationSession(
        dataset_path=dataset_path,
        events_path=tmp_path / "events.csv",
        curator="alice",
        journals=["Nature"],
    )
    assert set(session.queue) == {"rec1", "rec2"}

    obscure_session = CurationSession(
        dataset_path=dataset_path,
        events_path=tmp_path / "events.csv",
        curator="alice",
        journals=["Obscure Journal"],
    )
    assert set(obscure_session.queue) == {"rec4"}

    multi_session = CurationSession(
        dataset_path=dataset_path,
        events_path=tmp_path / "events.csv",
        curator="alice",
        journals=["Science", "Obscure Journal"],
    )
    assert set(multi_session.queue) == {"rec3", "rec4"}


def test_score_band_filter_splits_high_and_low(tmp_path):
    dataset_path = _write_dataset_for_filters(tmp_path / "canonical_dataset.csv")
    session = CurationSession(
        dataset_path=dataset_path,
        events_path=tmp_path / "events.csv",
        curator="alice",
        bulk_score_lookup=_FILTER_SCORE_LOOKUP,
        score_band=[1],  # top half: 150.0, 200.0 -> rec2, rec3
        n_score_bands=2,
    )
    assert set(session.queue) == {"rec2", "rec3"}


def test_needs_screening_only_filter(tmp_path):
    dataset_path = _write_dataset_for_filters(tmp_path / "canonical_dataset.csv")
    session = CurationSession(
        dataset_path=dataset_path,
        events_path=tmp_path / "events.csv",
        curator="alice",
        screening_lookup=_FILTER_SCREENING_LOOKUP,
        needs_screening_only=True,
    )
    assert set(session.queue) == {"rec1"}


def test_diversity_stats_counts_trusted_prior_labels(tmp_path):
    dataset_path = _write_dataset_with_mixed_trust(tmp_path / "canonical_dataset.csv")
    session = CurationSession(dataset_path=dataset_path, events_path=tmp_path / "events.csv", curator="alice")

    stats = session.diversity_stats()

    # rec1 (human_curated positive, J1) and rec2 (registry_confirmed negative, J2) count;
    # rec3 (heuristic_candidate, unreviewed) does not, even though its label is "positive".
    assert stats["n_journals_covered"] == 2
    assert stats["n_journals_total"] == 4
    assert stats["per_journal_counts"].loc["J1", "positive"] == 1
    assert stats["per_journal_counts"].loc["J2", "negative"] == 1
    assert "J3" not in stats["per_journal_counts"].index


def test_diversity_stats_reflects_live_session_decisions_before_materialize(tmp_path):
    # rec3 starts as heuristic_candidate/positive (not yet "confirmed") -- deciding it via the
    # app in THIS session must move the dashboard immediately, without running curate materialize.
    dataset_path = _write_dataset_with_mixed_trust(tmp_path / "canonical_dataset.csv")
    session = CurationSession(
        dataset_path=dataset_path, events_path=tmp_path / "events.csv", curator="alice"
    )
    before = session.diversity_stats()
    assert "J3" not in before["per_journal_counts"].index

    while session.current_record() is not None and session.current_record()["record_id"] != "rec3":
        session.record_decision("skipped")
    session.record_decision("negative")  # decide rec3

    after = session.diversity_stats()
    assert after["per_journal_counts"].loc["J3", "negative"] == 1
    assert after["n_journals_covered"] == before["n_journals_covered"] + 1


def test_score_band_summary_reports_real_ranges_and_curated_counts(tmp_path):
    dataset_path = _write_dataset_for_filters(tmp_path / "canonical_dataset.csv")
    session = CurationSession(
        dataset_path=dataset_path,
        events_path=tmp_path / "events.csv",
        curator="alice",
        bulk_score_lookup=_FILTER_SCORE_LOOKUP,  # PMC1:10, PMC2:200, PMC3:150, PMC4:5
        n_score_bands=2,
    )

    summary = session.score_band_summary()

    assert [s["band"] for s in summary] == [0, 1]
    low, high = summary
    assert low["min_score"] == 5.0 and low["max_score"] == 10.0
    assert high["min_score"] == 150.0 and high["max_score"] == 200.0
    assert low["total"] == 2 and high["total"] == 2
    # nothing decided yet -- all zero
    assert low["confirmed"] == 0 and high["confirmed"] == 0


def test_score_band_summary_reflects_confirmed_decisions(tmp_path):
    dataset_path = _write_dataset_for_filters(tmp_path / "canonical_dataset.csv")
    session = CurationSession(
        dataset_path=dataset_path,
        events_path=tmp_path / "events.csv",
        curator="alice",
        bulk_score_lookup=_FILTER_SCORE_LOOKUP,
        n_score_bands=2,
    )
    session.record_decision("negative")  # decides rec1 (PMC1, score 10 -> low band)

    summary = session.score_band_summary()
    low = next(s for s in summary if s["band"] == 0)
    assert low["confirmed"] == 1


def test_go_back_and_go_forward_navigate_without_changing_remaining(tmp_path):
    dataset_path = _write_dataset(tmp_path / "canonical_dataset.csv")
    session = CurationSession(
        dataset_path=dataset_path, events_path=tmp_path / "events.csv", curator="alice"
    )

    assert not session.can_go_back()
    session.record_decision("positive")  # decides rec1, now on rec2
    assert session.current_record()["record_id"] == "rec2"
    assert session.stats() == {"total": 3, "decided": 1, "remaining": 2}

    assert session.can_go_back()
    session.go_back()
    assert session.current_record()["record_id"] == "rec1"
    # remaining/decided must NOT change just from looking backward
    assert session.stats() == {"total": 3, "decided": 1, "remaining": 2}

    assert session.can_go_forward()
    session.go_forward()
    assert session.current_record()["record_id"] == "rec2"
    assert not session.can_go_forward()  # back at the frontier, nothing further to re-approach


def test_go_forward_is_capped_at_frontier_not_full_queue(tmp_path):
    dataset_path = _write_dataset(tmp_path / "canonical_dataset.csv")
    session = CurationSession(
        dataset_path=dataset_path, events_path=tmp_path / "events.csv", curator="alice"
    )
    session.go_forward()  # nothing decided yet -- must be a no-op, not skip ahead undecided
    assert session.current_record()["record_id"] == "rec1"


def test_revisiting_and_redeciding_a_record_advances_past_the_original_frontier(tmp_path):
    dataset_path = _write_dataset(tmp_path / "canonical_dataset.csv")
    session = CurationSession(
        dataset_path=dataset_path, events_path=tmp_path / "events.csv", curator="alice"
    )
    session.record_decision("positive")  # rec1 -> positive, now on rec2
    session.go_back()  # back to rec1
    session.record_decision("negative")  # change mind on rec1 -> negative, advances to rec2 again

    assert session.current_record()["record_id"] == "rec2"
    events = pd.read_csv(tmp_path / "events.csv")
    rec1_events = events[events["record_id"] == "rec1"]
    assert list(rec1_events["decision"]) == ["positive", "negative"]  # both kept, append-only


def test_current_record_prior_decision_reflects_latest_this_session(tmp_path):
    dataset_path = _write_dataset(tmp_path / "canonical_dataset.csv")
    session = CurationSession(
        dataset_path=dataset_path, events_path=tmp_path / "events.csv", curator="alice"
    )
    assert session.current_record_prior_decision() is None  # never decided yet

    session.record_decision("positive")
    session.go_back()
    assert session.current_record_prior_decision() == "positive"

    session.record_decision("negative")  # overwrite while revisiting
    session.go_back()
    assert session.current_record_prior_decision() == "negative"
