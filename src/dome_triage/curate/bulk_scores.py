"""Joins bulk-pool scoring/screening columns onto canonical/session rows for the Curate app's
filters and diversity dashboard -- the mirror image of pipeline/steps.py's
`_build_existing_label_lookup`/`_annotate_already_curated` (which join canonical *labels* onto the
bulk pool, for score-bulk-match's reporting columns). Here it's the opposite direction: bulk-pool
*scores* joined onto canonical rows, so the Curate app can filter/display them without
`canonical_dataset.csv` itself ever gaining a `match_score__bm25`-style column (Pydantic's
`extra='ignore'` already drops those on merge -- a deliberate choice, not an accident, kept that
way here too).

Deliberately does NOT import from `pipeline/steps.py`, which transitively pulls in `torch` via
`keywords/keybert_extract.py` -- the Streamlit process shouldn't pay that import cost just to
build a lookup dict.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

_ID_FIELDS = ("pmcid", "pmid", "doi")


def _existing_usecols(path: Path, wanted: list[str]) -> list[str]:
    header = pd.read_csv(path, nrows=0).columns
    return [c for c in wanted if c in header]


def load_bulk_score_lookup(
    scored_path: Path,
    score_col: str = "match_score__bm25",
    classification_col: str = "match_classification__bm25",
) -> dict[str, tuple[float, str]]:
    """Maps every pmcid/pmid/doi in `bulk_candidates_scored.csv` to (score, classification).
    Reads only the columns needed -- the file is ~1.7GB/27 columns at 744k+ rows; loading
    title/abstract here would be a multi-GB cost just to build a lookup dict. Returns `{}`
    gracefully if `scored_path` doesn't exist (Step 12 hasn't been run yet) or `score_col` is
    missing (e.g. a different scorer was chosen than the caller's default)."""
    scored_path = Path(scored_path)
    if not scored_path.exists():
        return {}

    usecols = _existing_usecols(scored_path, [*_ID_FIELDS, score_col, classification_col])
    if score_col not in usecols:
        return {}
    has_classification = classification_col in usecols

    df = pd.read_csv(scored_path, usecols=usecols, dtype=str)
    scores = pd.to_numeric(df[score_col], errors="coerce")
    classifications = df[classification_col] if has_classification else pd.Series([""] * len(df))

    lookup: dict[str, tuple[float, str]] = {}
    for id_field in _ID_FIELDS:
        if id_field not in df.columns:
            continue
        mask = df[id_field].notna() & (df[id_field] != "")
        for value, score, classification in zip(df.loc[mask, id_field], scores[mask], classifications[mask]):
            lookup.setdefault(value, (score, classification or ""))
    return lookup


def annotate_bulk_scores(
    dataset: pd.DataFrame,
    lookup: dict[str, tuple[float, str]],
    score_out_col: str = "bulk_match_score",
    classification_out_col: str = "bulk_match_classification",
) -> pd.DataFrame:
    """Vectorized pmcid->pmid->doi fallback join (`.map()`, not `.iterrows()` -- this codebase
    learned the hard way that row-by-row is too slow even at bulk-pool scale; here `dataset` is
    small, but the pattern stays consistent with `_annotate_already_curated`). Returns a copy;
    never writes back to `dataset` or to disk."""
    dataset = dataset.copy()
    score_lookup = {k: v[0] for k, v in lookup.items()}
    classification_lookup = {k: v[1] for k, v in lookup.items()}

    score = None
    classification = None
    for id_field in _ID_FIELDS:
        if id_field not in dataset.columns:
            continue
        mapped_score = dataset[id_field].map(score_lookup)
        mapped_classification = dataset[id_field].map(classification_lookup)
        score = mapped_score if score is None else score.fillna(mapped_score)
        classification = (
            mapped_classification if classification is None else classification.fillna(mapped_classification)
        )

    dataset[score_out_col] = score
    dataset[classification_out_col] = classification.fillna("") if classification is not None else ""
    return dataset


def load_screening_lookup(screened_path: Path) -> dict[str, bool]:
    """Maps pmcid/pmid/doi -> `needs_screening` from `clear_negative_candidates_screened.csv`
    (Step 14b). Returns `{}` gracefully if `screened_path` doesn't exist (screening hasn't been
    run) or the column is missing."""
    screened_path = Path(screened_path)
    if not screened_path.exists():
        return {}

    usecols = _existing_usecols(screened_path, [*_ID_FIELDS, "needs_screening"])
    if "needs_screening" not in usecols:
        return {}

    df = pd.read_csv(screened_path, usecols=usecols, dtype=str)
    flags = df["needs_screening"].isin(["True", "true", "1"])

    lookup: dict[str, bool] = {}
    for id_field in _ID_FIELDS:
        if id_field not in df.columns:
            continue
        mask = df[id_field].notna() & (df[id_field] != "")
        for value, flag in zip(df.loc[mask, id_field], flags[mask]):
            lookup.setdefault(value, bool(flag))
    return lookup


def annotate_screening(dataset: pd.DataFrame, lookup: dict[str, bool], out_col: str = "needs_screening") -> pd.DataFrame:
    """Same fallback-join pattern as `annotate_bulk_scores`, for the boolean screening flag."""
    dataset = dataset.copy()
    flag = None
    for id_field in _ID_FIELDS:
        if id_field not in dataset.columns:
            continue
        mapped = dataset[id_field].map(lookup)
        flag = mapped if flag is None else flag.fillna(mapped)
    dataset[out_col] = (flag.fillna(False) if flag is not None else pd.Series(False, index=dataset.index)).astype(bool)
    return dataset
