"""Core domain models.

Money is stored as integer minor units (paise) to avoid floating-point rounding.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify(value: str, max_length: int = 60) -> str:
    slug = _SLUG_RE.sub("-", value.lower()).strip("-")
    return slug[:max_length].strip("-") or "item"


def utcnow() -> datetime:
    return datetime.now(UTC)


def format_price(minor_units: int, currency: str = "INR") -> str:
    symbol = "₹" if currency == "INR" else f"{currency} "
    rupees, paise = divmod(minor_units, 100)
    return f"{symbol}{rupees:,}" if paise == 0 else f"{symbol}{rupees:,}.{paise:02d}"


class Product(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str = Field(description="Stable slug, unique within the business")
    name: str = Field(min_length=1, max_length=120, description="English name")
    name_local: str | None = Field(None, max_length=120, description="Name as written by the owner")
    description: str = Field("", max_length=500)
    price_minor: int = Field(ge=0, description="Price in minor units (paise)")
    unit: str = Field("each", max_length=40, description="e.g. 'per kg', 'per dozen', 'each'")
    tags: list[str] = Field(default_factory=list, max_length=12)
    available: bool = True

    @property
    def price_display(self) -> str:
        return format_price(self.price_minor)


class Business(BaseModel):
    model_config = ConfigDict(frozen=True)

    slug: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,59}$")
    name: str = Field(min_length=1, max_length=120)
    owner_name: str | None = Field(None, max_length=120)
    category: str = Field(max_length=60)
    description: str = Field("", max_length=1000)
    city: str = Field(max_length=80)
    service_areas: list[str] = Field(default_factory=list, description="Cities, localities or PIN codes served")
    languages: list[str] = Field(default_factory=lambda: ["English"])
    currency: str = "INR"
    products: list[Product] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utcnow)

    def product(self, product_id: str) -> Product | None:
        return next((p for p in self.products if p.id == product_id), None)

    def delivers_to(self, location: str) -> bool:
        needle = location.strip().lower()
        if not needle:
            return False
        areas = [a.lower() for a in [self.city, *self.service_areas]]
        return any(needle == a or needle in a or a in needle for a in areas)


class EnquirySource(StrEnum):
    WEB_FORM = "web_form"
    AI_AGENT = "ai_agent"


class EnquiryStatus(StrEnum):
    NEW = "new"
    REPLIED = "replied"


class EnquiryItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    product_id: str = Field(max_length=80)
    quantity: str = Field(max_length=40, description="Free text, e.g. '2 kg' or '3'")


class NewEnquiry(BaseModel):
    """Input for creating an enquiry, from either a web form or an AI agent."""

    business_slug: str
    customer_name: str = Field(min_length=1, max_length=120)
    customer_email: EmailStr
    message: str = Field(min_length=1, max_length=2000)
    items: list[EnquiryItem] = Field(default_factory=list, max_length=20)
    delivery_location: str | None = Field(None, max_length=200)
    needed_by: str | None = Field(None, max_length=80)
    source: EnquirySource = EnquirySource.WEB_FORM
    agent_name: str | None = Field(None, max_length=80, description="Which AI assistant sent it, if any")

    @field_validator("customer_name", "message", "delivery_location", "needed_by", "agent_name")
    @classmethod
    def _strip(cls, value: str | None) -> str | None:
        return value.strip() if isinstance(value, str) else value


class Enquiry(NewEnquiry):
    model_config = ConfigDict(frozen=True)

    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    status: EnquiryStatus = EnquiryStatus.NEW
    reply_text: str | None = None
    created_at: datetime = Field(default_factory=utcnow)
    replied_at: datetime | None = None


class ContactMessage(BaseModel):
    """Message from the site-wide contact form, delivered to the domain mailbox."""

    name: str = Field(min_length=1, max_length=120)
    email: EmailStr
    message: str = Field(min_length=1, max_length=4000)
