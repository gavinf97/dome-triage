"""Relevance-matching algorithms for scoring candidate papers against the curated keyword
lexicon. Multiple implementations, empirically compared (scoring_bakeoff.py) rather than one
hardcoded method -- this is a genuine open methodological question, trialled the same way the
later LLM backend choice is.

All three score a whole corpus against the lexicon at once (`score_corpus`), not one document at
a time -- BM25 and TF-IDF cosine both need the full corpus to compute their term statistics
(IDF), so a per-document API would force rebuilding those statistics on every call.
"""

from __future__ import annotations

from typing import Protocol

import pandas as pd
from rank_bm25 import BM25Okapi
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from dome_triage.keywords.preprocess import clean_text

ScoredResult = tuple[float, list[str]]


class MatchScorer(Protocol):
    name: str

    def score_corpus(self, corpus_texts: list[str], lexicon_terms: list[str]) -> list[ScoredResult]: ...


def _find_matched_terms(text: str, lexicon_terms: list[str]) -> list[str]:
    lowered = text.lower()
    return [term for term in lexicon_terms if term.lower() in lowered]


class WeightedSumScorer:
    """Sum of each present lexicon term's weight (typically its TF-IDF discriminative_score).
    Fully transparent and cheap -- the simplest baseline to sanity-check the others against."""

    name = "weighted-sum"

    def __init__(self, term_weights: dict[str, float]):
        self.term_weights = term_weights

    def score_corpus(self, corpus_texts: list[str], lexicon_terms: list[str]) -> list[ScoredResult]:
        results = []
        for text in corpus_texts:
            matched = _find_matched_terms(text, lexicon_terms)
            total = sum(self.term_weights.get(term, 0.0) for term in matched)
            results.append((total, matched))
        return results


class Bm25Scorer:
    """Okapi BM25 (rank_bm25), scoring every document in the corpus against a pseudo-query built
    from the approved lexicon terms. BM25's own IDF + length-normalization naturally up-weights
    rare-but-consistent terms and down-weights matches driven purely by long abstracts -- a
    standard, well-understood IR relevance-ranking method."""

    name = "bm25"

    def score_corpus(self, corpus_texts: list[str], lexicon_terms: list[str]) -> list[ScoredResult]:
        tokenized_corpus = [clean_text(t).split() for t in corpus_texts]
        bm25 = BM25Okapi(tokenized_corpus)
        query_tokens = clean_text(" ".join(lexicon_terms)).split()
        scores = bm25.get_scores(query_tokens)
        matched_terms = [_find_matched_terms(t, lexicon_terms) for t in corpus_texts]
        return list(zip((float(s) for s in scores), matched_terms))


class TfidfCosineScorer:
    """Cosine similarity between each document's TF-IDF vector (fit fresh on the corpus being
    scored) and a pseudo-document built from the approved lexicon terms."""

    name = "tfidf-cosine"

    def score_corpus(self, corpus_texts: list[str], lexicon_terms: list[str]) -> list[ScoredResult]:
        cleaned_corpus = [clean_text(t) for t in corpus_texts]
        pseudo_query = clean_text(" ".join(lexicon_terms))
        vectorizer = TfidfVectorizer()
        matrix = vectorizer.fit_transform([*cleaned_corpus, pseudo_query])
        doc_vectors, query_vector = matrix[:-1], matrix[-1]
        similarities = cosine_similarity(doc_vectors, query_vector).ravel()
        matched_terms = [_find_matched_terms(t, lexicon_terms) for t in corpus_texts]
        return list(zip((float(s) for s in similarities), matched_terms))


SCORERS: dict[str, type] = {
    "weighted-sum": WeightedSumScorer,
    "bm25": Bm25Scorer,
    "tfidf-cosine": TfidfCosineScorer,
}


def load_lexicon_terms_and_weights(lexicon_df) -> tuple[list[str], dict[str, float]]:
    """Extracts the approved term list + a weight per term (discriminative_score, defaulting to
    1.0 for terms without one, e.g. seed-only terms) from an approved keyword_lexicon.csv."""
    terms = lexicon_df["term"].dropna().tolist()
    has_score = "discriminative_score" in lexicon_df.columns
    weights = {
        row["term"]: (
            row["discriminative_score"]
            if has_score and pd.notna(row["discriminative_score"])
            else 1.0
        )
        for _, row in lexicon_df.iterrows()
    }
    return terms, weights
