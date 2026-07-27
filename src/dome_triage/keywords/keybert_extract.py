"""KeyBERT semantic keyword extraction. Config: configs/keybert.yaml. all-MiniLM-L6-v2 is small
(~90MB) and CPU-feasible per its published spec -- not yet live-verified in this environment
(no packages installed here); the first task after the Docker image builds should be a smoke
test (see docker/README.md).
"""

from __future__ import annotations

from collections import Counter

import pandas as pd
from keybert import KeyBERT

from dome_triage.keywords.preprocess import strip_html_tags


def extract_keybert_terms(documents: list[str], config: dict) -> pd.DataFrame:
    model = KeyBERT(model=config.get("model_name", "all-MiniLM-L6-v2"))
    ngram_range = tuple(config.get("keyphrase_ngram_range", [1, 3]))
    top_n = config.get("top_n", 15)
    use_mmr = config.get("use_mmr", True)
    diversity = config.get("diversity", 0.5)

    doc_frequency: Counter[str] = Counter()
    score_sum: dict[str, float] = {}

    for doc in documents:
        cleaned = strip_html_tags(doc)
        if not cleaned.strip():
            continue
        for term, score in model.extract_keywords(
            cleaned,
            keyphrase_ngram_range=ngram_range,
            top_n=top_n,
            use_mmr=use_mmr,
            diversity=diversity,
        ):
            doc_frequency[term] += 1
            score_sum[term] = score_sum.get(term, 0.0) + score

    rows = [
        {"term": term, "document_frequency": freq, "keybert_score_mean": score_sum[term] / freq}
        for term, freq in doc_frequency.items()
    ]
    return (
        pd.DataFrame(rows, columns=["term", "document_frequency", "keybert_score_mean"])
        .sort_values("document_frequency", ascending=False)
        .reset_index(drop=True)
    )
