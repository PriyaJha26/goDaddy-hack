import anthropic
import httpx
import pytest

from app.domain.errors import ExternalServiceError, ValidationFailed
from app.services.extraction import CatalogDraft, ClaudeCatalogExtractor, DraftProduct, detect_image_type
from tests.conftest import PNG_BYTES
from tests.fakes import FakeAnthropic


@pytest.mark.parametrize(
    ("data", "media_type"),
    [
        (b"\xff\xd8\xff\xe0rest", "image/jpeg"),
        (PNG_BYTES, "image/png"),
        (b"GIF89a....", "image/gif"),
        (b"RIFF\x00\x00\x00\x00WEBPVP8 ", "image/webp"),
    ],
)
def test_detect_image_type(data: bytes, media_type: str) -> None:
    assert detect_image_type(data) == media_type


def test_detect_image_type_rejects_non_images() -> None:
    with pytest.raises(ValidationFailed):
        detect_image_type(b"%PDF-1.7 not an image")


DRAFT = CatalogDraft(
    category="pickles",
    description="Pickles.",
    languages_seen=["Marathi"],
    products=[DraftProduct(name="Mango pickle", description="", price=450, unit="per kg", tags=["achar"])],
)


async def test_claude_extractor_sends_image_and_schema() -> None:
    fake = FakeAnthropic()
    fake.messages.parse_result = DRAFT
    extractor = ClaudeCatalogExtractor(fake, "claude-sonnet-5-5")  # type: ignore[arg-type]

    result = await extractor.extract(PNG_BYTES, owner_notes="Prices per kg")

    assert result == DRAFT
    [call] = fake.messages.calls
    assert call["model"] == "claude-sonnet-5-5"
    assert call["output_format"] is CatalogDraft
    image_block, text_block = call["messages"][0]["content"]
    assert image_block["source"]["media_type"] == "image/png"
    assert "<owner_notes>Prices per kg</owner_notes>" in text_block["text"]


async def test_claude_extractor_wraps_api_errors() -> None:
    fake = FakeAnthropic()
    fake.messages.error = anthropic.APIConnectionError(request=httpx.Request("POST", "https://api.anthropic.com"))
    with pytest.raises(ExternalServiceError):
        await ClaudeCatalogExtractor(fake, "m").extract(PNG_BYTES)  # type: ignore[arg-type]


async def test_claude_extractor_handles_unparseable_output() -> None:
    fake = FakeAnthropic()
    fake.messages.parse_result = None
    with pytest.raises(ExternalServiceError):
        await ClaudeCatalogExtractor(fake, "m").extract(PNG_BYTES)  # type: ignore[arg-type]


async def test_claude_extractor_validates_image_before_calling_api() -> None:
    fake = FakeAnthropic()
    with pytest.raises(ValidationFailed):
        await ClaudeCatalogExtractor(fake, "m").extract(b"not an image")  # type: ignore[arg-type]
    assert fake.messages.calls == []
