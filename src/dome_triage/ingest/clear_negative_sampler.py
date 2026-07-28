"""Separate true-negative sampler. The AI/ML-filtered bulk query (bulk_match.py) structurally
cannot produce a paper with zero AI/ML mention -- true negatives need a different source.

Design: sample several random week-long date windows across the target year range, fetch each
window in full via the same EpmcClient with a query excluding AI/ML terms, then downsample via
pandas. This is a pragmatic way to get genuine randomness without needing true random access
into a 40M+ record cursor-only API -- a documented design choice, not a hidden assumption.
"""

from __future__ import annotations

import random
from datetime import date, timedelta

import pandas as pd

from dome_triage.ingest.bulk_match import core_result_to_raw_record
from dome_triage.ingest.epmc_client import EpmcClient
from dome_triage.ingest.source_loaders import raw_records_to_dataframe

EXCLUDE_QUERY = (
    'SRC:MED NOT ("artificial intelligence" OR "machine learning" OR "deep learning" '
    'OR "neural network")'
)


def _random_week_windows(
    year_from: int, year_to: int, n_windows: int, seed: int = 42
) -> list[tuple[date, date]]:
    rng = random.Random(seed)
    start = date(year_from, 1, 1)
    end = date(year_to, 12, 25)
    span_days = (end - start).days

    windows = []
    for _ in range(n_windows):
        offset = rng.randint(0, span_days)
        window_start = start + timedelta(days=offset)
        window_end = window_start + timedelta(days=6)
        windows.append((window_start, window_end))
    return windows


def fetch_clear_negatives(
    client: EpmcClient,
    year_from: int,
    year_to: int,
    sample_size: int,
    n_windows: int = 20,
) -> pd.DataFrame:
    windows = _random_week_windows(year_from, year_to, n_windows)
    records = []
    for window_start, window_end in windows:
        query = f"({EXCLUDE_QUERY}) AND (FIRST_PDATE:[{window_start} TO {window_end}])"
        for result in client.search(query, result_type="core", show_progress=True):
            records.append(
                core_result_to_raw_record(
                    result,
                    source_name="clear_negative_sampler",
                    source_file=f"live_query:{window_start}_{window_end}",
                    label="negative",
                    label_confidence="heuristic_candidate",
                )
            )

    df = raw_records_to_dataframe(records)
    if len(df) > sample_size:
        df = df.sample(n=sample_size, random_state=42).reset_index(drop=True)
    return df
