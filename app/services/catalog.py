"""Business catalogue use cases: onboarding from a draft, lookup and search."""

from __future__ import annotations

from dataclasses import dataclass

from app.domain.errors import ConflictError, NotFoundError
from app.domain.models import Business, Product, slugify
from app.repositories.base import BusinessRepository
from app.services.extraction import CatalogDraft, CatalogExtractor
from app.services.search import SearchHit, search_products


@dataclass(frozen=True, slots=True)
class BusinessProfile:
    """What the owner confirms on the review screen before publishing."""

    name: str
    city: str
    category: str
    description: str
    service_areas: list[str]
    owner_name: str | None = None
    languages: tuple[str, ...] = ("English",)


def products_from_draft(draft: CatalogDraft) -> list[Product]:
    products: list[Product] = []
    seen: set[str] = set()
    for item in draft.products:
        base = slugify(item.name, max_length=50)
        product_id, n = base, 2
        while product_id in seen:
            product_id, n = f"{base}-{n}", n + 1
        seen.add(product_id)
        products.append(
            Product(
                id=product_id,
                name=item.name.strip()[:120],
                name_local=(item.name_local or None) and item.name_local.strip()[:120],
                description=item.description.strip()[:500],
                price_minor=max(0, round(item.price * 100)),
                unit=(item.unit or "each").strip()[:40],
                tags=sorted({t.strip().lower()[:40] for t in item.tags if t.strip()})[:12],
            )
        )
    return products


class CatalogService:
    def __init__(self, businesses: BusinessRepository, extractor: CatalogExtractor) -> None:
        self._businesses = businesses
        self._extractor = extractor

    async def draft_from_image(self, image: bytes, owner_notes: str = "") -> CatalogDraft:
        return await self._extractor.extract(image, owner_notes)

    async def publish(self, profile: BusinessProfile, products: list[Product]) -> Business:
        slug = slugify(profile.name)
        if await self._businesses.get(slug) is not None:
            raise ConflictError(f"A business called '{profile.name}' already exists. Choose another name.")
        business = Business(
            slug=slug,
            name=profile.name.strip(),
            owner_name=profile.owner_name,
            category=profile.category.strip(),
            description=profile.description.strip(),
            city=profile.city.strip(),
            service_areas=[a.strip() for a in profile.service_areas if a.strip()],
            languages=list(profile.languages),
            products=products,
        )
        await self._businesses.save(business)
        return business

    async def get(self, slug: str) -> Business:
        business = await self._businesses.get(slug)
        if business is None:
            raise NotFoundError(f"No business found with id '{slug}'.")
        return business

    async def list_all(self) -> list[Business]:
        return await self._businesses.list_all()

    async def search(self, query: str, location: str | None = None, limit: int = 5) -> list[SearchHit]:
        return search_products(await self._businesses.list_all(), query, location, limit)
