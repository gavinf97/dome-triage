from dome_triage.ingest.bulk_match import core_result_to_raw_record

# Field structure confirmed via a live Europe PMC resultType=core fetch.
SAMPLE_RESULT = {
    "pmid": "35582656",
    "pmcid": "PMC8962827",
    "doi": "10.1109/tim.2021.3130675",
    "title": "Deep Generative Learning-Based 1-SVM Detectors.",
    "abstractText": "A sample blood test has recently become an important tool.",
    "authorString": "Dairi A, Harrou F, Sun Y.",
    "journalInfo": {"journal": {"title": "IEEE transactions on instrumentation and measurement"}},
    "pubYear": "2022",
    "isOpenAccess": "Y",
    "pubTypeList": {"pubType": ["research-article", "Journal Article"]},
    "keywordList": {"keyword": ["Deep Learning", "Covid-19"]},
    "inEPMC": "Y",
    "meshHeadingList": {
        "meshHeading": [{"majorTopic_YN": "Y", "descriptorName": "Machine Learning"}]
    },
}


def test_core_result_to_raw_record_maps_all_fields():
    record = core_result_to_raw_record(SAMPLE_RESULT, source_name="bulk_match_2022", source_file="test.jsonl")

    assert record.pmcid == "PMC8962827"
    assert record.pmid == "35582656"
    assert record.doi == "10.1109/tim.2021.3130675"
    assert record.title == "Deep Generative Learning-Based 1-SVM Detectors."
    assert record.journal == "IEEE transactions on instrumentation and measurement"
    assert record.year == 2022
    assert record.is_open_access is True
    assert record.pub_types == ["research-article", "Journal Article"]
    assert record.keywords_author == ["Deep Learning", "Covid-19"]
    assert record.mesh_headings == ["Machine Learning"]
    assert record.fulltext_available is True
    assert record.label == "unlabeled"
    assert record.label_confidence == "unscored"


def test_core_result_to_raw_record_accepts_label_override():
    record = core_result_to_raw_record(
        SAMPLE_RESULT,
        source_name="clear_negative_sampler",
        source_file="test",
        label="negative",
        label_confidence="heuristic_candidate",
    )
    assert record.label == "negative"
    assert record.label_confidence == "heuristic_candidate"


def test_core_result_to_raw_record_handles_missing_optional_fields():
    minimal_result = {"pmid": "12345678", "title": "A paper"}
    record = core_result_to_raw_record(minimal_result, source_name="test", source_file="test")

    assert record.pmid == "12345678"
    assert record.pmcid is None
    assert record.year is None
    assert record.is_open_access is None
    assert record.mesh_headings == []
    assert record.pub_types == []
    assert record.fulltext_available is False
