from app.domain.models import Product
from app.services.search import search_products, tokenize
from tests.conftest import make_business


def test_tokenize_drops_stopwords_and_folds_plurals() -> None:
    tokens = tokenize("I need some pickles for Diwali")
    assert {"pickles", "pickle", "diwali"} <= tokens
    assert "need" not in tokens and "for" not in tokens


def test_finds_product_by_regional_synonym_tag() -> None:
    hits = search_products([make_business()], "aam ka achar")
    assert hits[0].product.id == "mango-pickle"


def test_name_match_ranks_above_partial_match() -> None:
    hits = search_products([make_business()], "mango pickle")
    assert [h.product.id for h in hits] == ["mango-pickle", "lemon-pickle"]


def test_location_filter_excludes_businesses_that_do_not_deliver() -> None:
    assert search_products([make_business()], "pickle", location="Kothrud")
    assert search_products([make_business()], "pickle", location="Chennai") == []


def test_unavailable_products_are_excluded() -> None:
    business = make_business(
        products=[Product(id="p", name="Mango pickle", price_minor=1, available=False, tags=["pickle"])]
    )
    assert search_products([business], "mango pickle") == []


def test_empty_or_stopword_query_returns_nothing() -> None:
    assert search_products([make_business()], "   ") == []
    assert search_products([make_business()], "I want to buy") == []


def test_limit_is_respected() -> None:
    assert len(search_products([make_business()], "pickle", limit=1)) == 1
