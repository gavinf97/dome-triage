from dome_triage.keywords.scoring import Bm25Scorer, TfidfCosineScorer, WeightedSumScorer

RELEVANT_DOC = (
    "We trained a random forest classifier on genomic data to predict cancer subtype "
    "with high accuracy using machine learning."
)
IRRELEVANT_DOC = "This paper reviews the history of impressionist painting in 19th century France."
LEXICON_TERMS = ["random forest", "machine learning", "classifier", "accuracy"]

# BM25/TF-IDF need more than 2 documents to give a meaningful signal: with exactly 2 docs where
# every term's document-frequency is exactly N/2, the classic Robertson-Sparck-Jones IDF term
# rank_bm25 uses degenerates to exactly zero for every term (a real, documented BM25 property at
# tiny corpus sizes, not specific to this codebase) -- so corpus-level scorer tests use a slightly
# larger, more realistic corpus.
FILLER_DOCS = [
    "A cross-sectional survey of patient satisfaction across three hospitals.",
    "We describe a new surgical technique for knee replacement in elderly patients.",
]


def test_weighted_sum_scorer_ranks_relevant_document_higher():
    weights = {t: 1.0 for t in LEXICON_TERMS}
    scorer = WeightedSumScorer(weights)
    results = scorer.score_corpus([RELEVANT_DOC, IRRELEVANT_DOC], LEXICON_TERMS)

    relevant_score, relevant_matches = results[0]
    irrelevant_score, irrelevant_matches = results[1]

    assert relevant_score > irrelevant_score
    assert irrelevant_score == 0
    assert "machine learning" in relevant_matches
    assert irrelevant_matches == []


def test_weighted_sum_scorer_respects_term_weights():
    scorer = WeightedSumScorer({"machine learning": 5.0, "classifier": 1.0})
    score, matched = scorer.score_corpus([RELEVANT_DOC], ["machine learning", "classifier"])[0]
    assert score == 6.0
    assert set(matched) == {"machine learning", "classifier"}


def test_bm25_scorer_ranks_relevant_document_higher():
    scorer = Bm25Scorer()
    corpus = [RELEVANT_DOC, IRRELEVANT_DOC, *FILLER_DOCS]
    results = scorer.score_corpus(corpus, LEXICON_TERMS)
    assert results[0][0] > results[1][0]


def test_tfidf_cosine_scorer_ranks_relevant_document_higher():
    scorer = TfidfCosineScorer()
    corpus = [RELEVANT_DOC, IRRELEVANT_DOC, *FILLER_DOCS]
    results = scorer.score_corpus(corpus, LEXICON_TERMS)
    assert results[0][0] > results[1][0]
