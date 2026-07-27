"""Text preprocessing shared by TF-IDF and KeyBERT extraction.

Strips the inline pseudo-HTML section tags confirmed present in EPMC abstracts (e.g.
"<h4>Background</h4>") before tokenizing -- left unstripped, these polluted the original TF-IDF
pass: categorized_terms.csv (MLit-Triage-Nextflow) contains "h4"/"background"/"http" among its
top terms. Stripping them here is a direct fix over the original, not just a port.
"""

from __future__ import annotations

import re
from typing import Optional

import nltk
from nltk.corpus import stopwords
from nltk.stem import WordNetLemmatizer
from nltk.tokenize import word_tokenize

_HTML_TAG_RE = re.compile(r"<[^>]+>")
_NON_ALPHA_RE = re.compile(r"[^a-zA-Z\s-]")

_lemmatizer = WordNetLemmatizer()
_NLTK_RESOURCES = {
    "stopwords": "corpora/stopwords",
    "punkt_tab": "tokenizers/punkt_tab",
    "wordnet": "corpora/wordnet",
    "omw-1.4": "corpora/omw-1.4",
}


def ensure_nltk_data() -> None:
    """Downloads required NLTK corpora if missing. Baked into the Docker image at build time
    (see docker/Dockerfile.cpu) so this is a no-op there; kept here as a safety net for local
    (non-Docker) development."""
    for package, resource_path in _NLTK_RESOURCES.items():
        try:
            nltk.data.find(resource_path)
        except LookupError:
            nltk.download(package, quiet=True)


def strip_html_tags(text: str) -> str:
    return _HTML_TAG_RE.sub(" ", text)


def clean_text(text: str, extra_stopwords: Optional[set[str]] = None) -> str:
    """Strip HTML tags, tokenize, lowercase, drop stopwords/short/non-alpha tokens, lemmatize."""
    if not text:
        return ""
    ensure_nltk_data()
    stop = set(stopwords.words("english")) | (extra_stopwords or set())

    text = strip_html_tags(text)
    text = _NON_ALPHA_RE.sub(" ", text)
    tokens = word_tokenize(text.lower())
    tokens = [
        _lemmatizer.lemmatize(token)
        for token in tokens
        if token not in stop and len(token) > 2
    ]
    return " ".join(tokens)
