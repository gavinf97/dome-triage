from dome_triage.keywords.scoring import WeightedSumScorer
from dome_triage.keywords.scoring_bakeoff import run_bakeoff

TEXTS = [
    "We trained a random forest classifier on genomic data to predict cancer subtype.",
    "This paper reviews the history of impressionist painting in France.",
    "Machine learning models including deep neural networks were applied to protein prediction.",
    "A cross-sectional survey of patient satisfaction in three hospitals.",
]
TRUE_LABELS = [1, 0, 1, 0]
LEXICON_TERMS = ["random forest", "machine learning", "neural network", "classifier"]


def test_run_bakeoff_reports_one_row_per_scorer():
    scorers = {"weighted-sum": WeightedSumScorer({t: 1.0 for t in LEXICON_TERMS})}
    report = run_bakeoff(scorers, TEXTS, TRUE_LABELS, LEXICON_TERMS)

    assert len(report) == 1
    assert report.iloc[0]["scorer"] == "weighted-sum"
    assert {"auroc", "correlation_with_label", "precision_recall_at_quantiles"}.issubset(
        report.columns
    )


def test_run_bakeoff_gives_perfect_auroc_for_a_clearly_separable_scorer():
    scorers = {"weighted-sum": WeightedSumScorer({t: 1.0 for t in LEXICON_TERMS})}
    report = run_bakeoff(scorers, TEXTS, TRUE_LABELS, LEXICON_TERMS)
    assert report.iloc[0]["auroc"] == 1.0


def test_run_bakeoff_sorts_by_auroc_descending():
    good_scorer = WeightedSumScorer({t: 1.0 for t in LEXICON_TERMS})
    bad_scorer = WeightedSumScorer({})  # never matches anything -- score is always 0
    report = run_bakeoff(
        {"good": good_scorer, "bad": bad_scorer}, TEXTS, TRUE_LABELS, LEXICON_TERMS
    )
    assert report.iloc[0]["scorer"] == "good"
