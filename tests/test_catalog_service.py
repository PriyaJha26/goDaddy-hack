import pytest

from app.domain.errors import ConflictError, NotFoundError
from app.repositories.sqlite import SqliteBusinessRepository
from app.services.catalog import BusinessProfile, CatalogService, products_from_draft
from app.services.extraction import CatalogDraft, DraftProduct, SampleCatalogExtractor
from tests.conftest import PNG_BYTES


def draft_with(*products: DraftProduct) -> CatalogDraft:
    return CatalogDraft(category="pickles", description="d", languages_seen=["Marathi"], products=list(products))


def item(name: str, price: float = 100, tags: list[str] | None = None) -> DraftProduct:
    return DraftProduct(name=name, description="", price=price, unit="per kg", tags=tags or [])


def test_products_from_draft_converts_price_to_paise() -> None:
    [product] = products_from_draft(draft_with(item("Mango pickle", 450.5)))
    assert product.price_minor == 45050
    assert product.id == "mango-pickle"


def test_products_from_draft_deduplicates_ids_and_clamps_negative_prices() -> None:
    products = products_from_draft(draft_with(item("Pickle"), item("Pickle", -5)))
    assert [p.id for p in products] == ["pickle", "pickle-2"]
    assert products[1].price_minor == 0


def test_products_from_draft_normalises_tags() -> None:
    [product] = products_from_draft(draft_with(item("X", tags=[" Achar ", "achar", "", "PICKLE"])))
    assert product.tags == ["achar", "pickle"]


@pytest.fixture
def service(business_repo: SqliteBusinessRepository) -> CatalogService:
    return CatalogService(business_repo, SampleCatalogExtractor())


PROFILE = BusinessProfile(
    name="Aaji's Pickles", city="Pune", category="pickles", description="d", service_areas=["Kothrud", " "]
)


async def test_publish_then_get_and_search(service: CatalogService) -> None:
    draft = await service.draft_from_image(PNG_BYTES)
    business = await service.publish(PROFILE, products_from_draft(draft))
    assert business.slug == "aaji-s-pickles"
    assert business.service_areas == ["Kothrud"]
    assert (await service.get(business.slug)).name == "Aaji's Pickles"
    hits = await service.search("aam ka achar", location="Kothrud")
    assert hits[0].product.name == "Mango pickle"


async def test_publish_rejects_duplicate_name(service: CatalogService) -> None:
    await service.publish(PROFILE, [])
    with pytest.raises(ConflictError):
        await service.publish(PROFILE, [])


async def test_get_unknown_business_raises(service: CatalogService) -> None:
    with pytest.raises(NotFoundError):
        await service.get("missing")
