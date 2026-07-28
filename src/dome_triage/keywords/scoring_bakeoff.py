"""Empirically compares MatchScorer implementations against the already-known-labeled ~4,320
consolidated records (real positive/negative ground truth) -- answers "which scoring method
actually separates known positives from known negatives" before any scorer is trusted to rank
the much larger unlabeled bulk pool from ingest/bulk_match.py.
"""

from __future__ import annotations

import pandas as pd
from sklearn.metrics import roc_auc_score

from dome_triage.keywords.scoring import MatchScorer


def _precision_recall_at_quantile(scores: pd.Series, true_labels: pd.Series, quantile: float) -> tuple[float, float]:
    threshold = scores.quantile(quantile)
    predicted_positive = scores >= threshold
    true_positive = int((predicted_positive & (true_labels == 1)).sum())
    false_positive = int((predicted_positive & (true_labels == 0)).sum())
    false_negative = int((~predicted_positive & (true_labels == 1)).sum())

    precision = true_positive / (true_positive + false_positive) if (true_positive + false_positive) else float("nan")
    recall = true_positive / (true_positive + false_negative) if (true_positive + false_negative) else float("nan")
    return precision, recall


def run_bakeoff(
    scorers: dict[str, MatchScorer],
    texts: list[str],
    true_labels: list[int],
    lexicon_terms: list[str],
) -> pd.DataFrame:
    """`true_labels` must be 1 for positive / 0 for negative -- already-labeled records only."""
    labels = pd.Series(true_labels)
    rows = []

    for name, scorer in scorers.items():
        scored = scorer.score_corpus(texts, lexicon_terms)
        scores = pd.Series([s for s, _ in scored])

        try:
            auroc = roc_auc_score(labels, scores)
        except ValueError:
            auroc = float("nan")  # e.g. only one class present in this sample

        quantile_report = []
        for quantile in (0.5, 0.75, 0.9):
            precision, recall = _precision_recall_at_quantile(scores, labels, quantile)
            quantile_report.append(f"q{int(quantile * 100)}: P={precision:.2f} R={recall:.2f}")

        rows.append(
            {
                "scorer": name,
                "auroc": auroc,
                "correlation_with_label": scores.corr(labels),
                "precision_recall_at_quantiles": "; ".join(quantile_report),
            }
        )

    return pd.DataFrame(rows).sort_values("auroc", ascending=False).reset_index(drop=True)
