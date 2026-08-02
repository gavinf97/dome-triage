"""Separate true-negative sampler. The AI/ML-filtered bulk query (bulk_match.py) structurally
cannot produce a paper with zero AI/ML mention -- true negatives need a different source.

Design: sample several random week-long date windows across the target year range, fetch each
window in full via the same EpmcClient with a query excluding AI/ML terms, then stratify-downsample
by journal x year via `sampling/stratified.py` (the same tested bucketing Step 13's bulk-pool
sampling uses) rather than a plain random sample -- so the resulting negative pool is diverse
across journals and years, not just whatever the random date windows happened to catch. This is a
pragmatic way to get genuine randomness without needing true random access into a 40M+ record
cursor-only API -- a documented design choice, not a hidden assumption.

**Data source, worth being explicit about**: `EXCLUDE_QUERY` below is a live query against the
*full* Europe PMC corpus via `EpmcClient.search()`, the structural inverse of `bulk_match.py`'s
`AI_ML_QUERY` (which requires "artificial intelligence"/"machine learning"; this requires their
absence). It never reads `bulk_candidates.csv` or any other local file -- every record here is
independently confirmed by EPMC's own search to not mention AI/ML terms at all, genuinely disjoint
from the 750k AI/ML-matched pool by construction, not a downsample or filter of it.
"""

from __future__ import annotations

import math
import random
from datetime import date, timedelta

import pandas as pd

from dome_triage.ingest.bulk_match import core_result_to_raw_record
from dome_triage.ingest.epmc_client import EpmcClient
from dome_triage.ingest.source_loaders import raw_records_to_dataframe
from dome_triage.sampling.stratified import build_strata, stratified_sample

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
    n_windows: int = 40,
    top_n_journals: int = 15,
    year_bucket_width: int = 5,
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
    print(f"clear_negative_sampler: {len(df)} raw candidates across {n_windows} live-EPMC "
          f"date windows before journal/year stratification")
    if len(df) <= sample_size:
        return df

    # Stratify by journal x year (build_strata/stratified_sample -- the same tested bucketing
    # Step 13's bulk-pool sampling uses; score_col=None since these candidates have no meaningful
    # lexicon score to band by -- they were explicitly selected for NOT matching it) so the
    # downsample is diverse, not just whatever the random date windows happened to catch.
    df["year"] = pd.to_numeric(df["year"], errors="coerce")
    strata_df = build_strata(
        df, score_col=None, top_n_journals=top_n_journals, year_bucket_width=year_bucket_width
    )
    strata_cols = ["journal_bucket", "year_bucket"]
    n_strata = strata_df[strata_cols].drop_duplicates().shape[0]
    cap_per_stratum = max(1, math.ceil(sample_size / n_strata)) if n_strata else sample_size
    sampled, report = stratified_sample(strata_df, strata_cols, cap_per_stratum, random_state=42)
    print(f"clear_negative_sampler: {n_strata} journal x year strata, cap_per_stratum="
          f"{cap_per_stratum} -> {len(sampled)} stratified candidates")
    print(report.to_string(index=False))

    if len(sampled) > sample_size:
        sampled = sampled.sample(n=sample_size, random_state=42)
    return sampled.drop(columns=strata_cols).reset_index(drop=True)
