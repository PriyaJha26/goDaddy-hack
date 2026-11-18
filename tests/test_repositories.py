from app.domain.models import Enquiry, EnquiryStatus
from app.repositories.sqlite import Database, SqliteBusinessRepository, SqliteEnquiryRepository
from tests.conftest import make_business


async def test_business_round_trip_and_upsert(business_repo: SqliteBusinessRepository) -> None:
    business = make_business()
    await business_repo.save(business)
    assert await business_repo.get(business.slug) == business

    renamed = business.model_copy(update={"name": "Aaji's Famous Pickles"})
    await business_repo.save(renamed)
    assert (await business_repo.get(business.slug)).name == "Aaji's Famous Pickles"
    assert await business_repo.count() == 1


async def test_missing_business_returns_none(business_repo: SqliteBusinessRepository) -> None:
    assert await business_repo.get("nope") is None


async def test_list_all_in_creation_order(business_repo: SqliteBusinessRepository) -> None:
    await business_repo.save(make_business("first"))
    await business_repo.save(make_business("second"))
    assert [b.slug for b in await business_repo.list_all()] == ["first", "second"]


async def test_enquiries_newest_first_and_update(
    business_repo: SqliteBusinessRepository, enquiry_repo: SqliteEnquiryRepository
) -> None:
    await business_repo.save(make_business())
    first = Enquiry(business_slug="aajis-pickles", customer_name="A", customer_email="a@example.com", message="1")
    second = Enquiry(business_slug="aajis-pickles", customer_name="B", customer_email="b@example.com", message="2")
    await enquiry_repo.save(first)
    await enquiry_repo.save(second)
    assert [e.customer_name for e in await enquiry_repo.list_recent()] == ["B", "A"]

    await enquiry_repo.save(first.model_copy(update={"status": EnquiryStatus.REPLIED}))
    assert (await enquiry_repo.get(first.id)).status is EnquiryStatus.REPLIED


async def test_migrations_are_idempotent(db: Database) -> None:
    await db.migrate()  # second run must be a no-op
    await SqliteBusinessRepository(db).save(make_business())
    await db.migrate()
    assert await SqliteBusinessRepository(db).count() == 1
