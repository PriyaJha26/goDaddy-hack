import pytest
from pydantic import ValidationError

from app.domain.models import NewEnquiry, format_price, slugify
from tests.conftest import make_business


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("Aaji's Pickles", "aaji-s-pickles"), ("  Meera's   Bakehouse!! ", "meera-s-bakehouse"), ("!!!", "item")],
)
def test_slugify(raw: str, expected: str) -> None:
    assert slugify(raw) == expected


@pytest.mark.parametrize(
    ("minor", "expected"), [(45000, "₹450"), (12050, "₹120.50"), (12345600, "₹123,456"), (0, "₹0")]
)
def test_format_price(minor: int, expected: str) -> None:
    assert format_price(minor) == expected


@pytest.mark.parametrize(
    ("location", "delivers"),
    [("Kothrud", True), ("kothrud, pune", True), ("411038", True), ("Pune", True), ("Mumbai", False), ("", False)],
)
def test_delivers_to(location: str, delivers: bool) -> None:
    assert make_business().delivers_to(location) is delivers


def test_business_product_lookup() -> None:
    business = make_business()
    assert business.product("mango-pickle").name == "Mango pickle"
    assert business.product("missing") is None


def test_new_enquiry_rejects_invalid_email() -> None:
    with pytest.raises(ValidationError):
        NewEnquiry(business_slug="x", customer_name="Priya", customer_email="not-an-email", message="hi")


def test_new_enquiry_strips_whitespace() -> None:
    enquiry = NewEnquiry(business_slug="x", customer_name="  Priya ", customer_email="p@example.com", message=" hi ")
    assert enquiry.customer_name == "Priya"
    assert enquiry.message == "hi"
