from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.config import Settings
from app.container import Container, build_container
from app.domain.models import Business, Product
from app.main import create_app
from app.repositories.sqlite import Database, SqliteBusinessRepository, SqliteEnquiryRepository
from app.services.extraction import SampleCatalogExtractor
from app.services.mailer import LoggingMailer
from app.services.replies import TemplateReplyDrafter

OWNER_PASSWORD = "correct horse battery staple"
# Smallest valid PNG header + padding; enough for magic-byte detection.
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


def make_business(slug: str = "aajis-pickles", **overrides) -> Business:
    data = {
        "slug": slug,
        "name": "Aaji's Pickles",
        "category": "homemade pickles",
        "description": "Pickles made in small batches.",
        "city": "Pune",
        "service_areas": ["Kothrud", "411038"],
        "languages": ["Marathi", "English"],
        "products": [
            Product(
                id="mango-pickle",
                name="Mango pickle",
                name_local="कैरीचे लोणचे",
                price_minor=45000,
                unit="per kg",
                tags=["mango pickle", "aam ka achar", "achar"],
            ),
            Product(
                id="lemon-pickle",
                name="Lemon pickle",
                price_minor=38000,
                unit="per kg",
                tags=["lemon pickle", "nimbu achar"],
            ),
        ],
    }
    data.update(overrides)
    return Business(**data)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        database_path=tmp_path / "test.db",
        seed_demo_data=False,
        owner_password=SecretStr(OWNER_PASSWORD),
        secret_key=SecretStr("test-secret-key-that-is-long-enough-123"),
        notify_email="hello@example.com",
        public_base_url="http://testserver",
        anthropic_api_key=None,
    )


@pytest.fixture
def mailer() -> LoggingMailer:
    return LoggingMailer()


@pytest.fixture
def container(settings: Settings, mailer: LoggingMailer) -> Container:
    return build_container(settings, mailer=mailer, extractor=SampleCatalogExtractor(), drafter=TemplateReplyDrafter())


@pytest.fixture
def client(settings: Settings, container: Container) -> Iterator[TestClient]:
    with TestClient(create_app(settings, container)) as test_client:
        yield test_client


@pytest.fixture
def seeded_client(client: TestClient, container: Container) -> TestClient:
    client.portal.call(container.businesses.save, make_business())
    return client


def login(client: TestClient) -> str:
    """Log in as the owner and return the CSRF token from the dashboard."""
    response = client.post("/owner/login", data={"password": OWNER_PASSWORD}, follow_redirects=True)
    assert response.status_code == 200
    match = re.search(r'name="csrf_token" value="([^"]+)"', response.text)
    assert match, "dashboard should render a CSRF token"
    return match.group(1)


@pytest.fixture
async def db(tmp_path: Path) -> Database:
    database = Database(tmp_path / "repo.db")
    await database.migrate()
    return database


@pytest.fixture
def business_repo(db: Database) -> SqliteBusinessRepository:
    return SqliteBusinessRepository(db)


@pytest.fixture
def enquiry_repo(db: Database) -> SqliteEnquiryRepository:
    return SqliteEnquiryRepository(db)
