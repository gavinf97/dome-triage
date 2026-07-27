"""Merges TF-IDF + KeyBERT extraction output with the categorized_terms.csv seed vocabulary
(MLit-Triage-Nextflow, 500 already human-vetted terms, schema Term/TF-IDF/Category -- confirmed)
into one candidate lexicon for human review at curate/pages/3_Keyword_Review.py. The reviewed
output is data/processed/keyword_lexicon.csv -- this is the "keyword trawl" checkpoint.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd


def load_seed_terms(path: str | Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    return df.rename(
        columns={"Term": "term", "TF-IDF": "seed_tfidf_score", "Category": "seed_category"}
    )


def build_candidate_lexicon(
    tfidf_df: pd.DataFrame,
    keybert_df: pd.DataFrame,
    seed_df: pd.DataFrame | None = None,
) -> pd.DataFrame:
    merged = pd.merge(tfidf_df, keybert_df, on="term", how="outer")
    if seed_df is not None and not seed_df.empty:
        merged = pd.merge(merged, seed_df, on="term", how="left")

    merged["review_status"] = "pending"
    merged["notes"] = ""

    sort_cols = [c for c in ("discriminative_score", "document_frequency") if c in merged.columns]
    if sort_cols:
        merged = merged.sort_values(by=sort_cols, ascending=False)
    return merged.reset_index(drop=True)
