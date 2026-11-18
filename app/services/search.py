"""Product search across businesses: a small, pure, deterministic ranking function.

Products carry English names plus tags generated at onboarding (e.g. "aam ka achar" is
tagged "mango pickle"), so an English query can find a product the owner wrote in Hindi.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.domain.models import Business, Product

# Latin letters/digits plus the Indic script blocks (Devanagari U+0900 through Sinhala U+0DFF).
_TOKEN_RE = re.compile("[a-z0-9ऀ-෿]+")
_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "buy",
        "by",
        "can",
        "delivered",
        "delivery",
        "do",
        "does",
        "for",
        "from",
        "get",
        "i",
        "in",
        "is",
        "it",
        "me",
        "my",
        "near",
        "need",
        "of",
        "on",
        "or",
        "order",
        "please",
        "some",
        "the",
        "to",
        "want",
        "where",
        "which",
        "who",
        "with",
    }
)

# Field weights: what the product *is* matters more than how it is described.
_W_NAME, _W_TAG, _W_CATEGORY, _W_DESCRIPTION = 4, 3, 2, 1


def tokenize(text: str) -> set[str]:
    tokens = {t for t in _TOKEN_RE.findall(text.lower()) if t not in _STOPWORDS and len(t) > 1}
    # Light plural folding so "pickles" matches "pickle".
    return tokens | {t[:-1] for t in tokens if t.endswith("s") and len(t) > 3}


@dataclass(frozen=True, slots=True)
class SearchHit:
    business: Business
    product: Product
    score: int


def _score(query: set[str], business: Business, product: Product) -> int:
    name = tokenize(f"{product.name} {product.name_local or ''}")
    tags = tokenize(" ".join(product.tags))
    category = tokenize(f"{business.category} {business.name}")
    description = tokenize(product.description)
    return (
        _W_NAME * len(query & name)
        + _W_TAG * len(query & tags)
        + _W_CATEGORY * len(query & category)
        + _W_DESCRIPTION * len(query & description)
    )


def search_products(
    businesses: list[Business], query: str, location: str | None = None, limit: int = 5
) -> list[SearchHit]:
    """Rank available products by relevance; optionally keep only businesses serving ``location``."""
    terms = tokenize(query)
    if not terms:
        return []
    hits = [
        SearchHit(business, product, score)
        for business in businesses
        if not location or business.delivers_to(location)
        for product in business.products
        if product.available and (score := _score(terms, business, product)) > 0
    ]
    hits.sort(key=lambda h: (-h.score, h.product.price_minor))
    return hits[:limit]
