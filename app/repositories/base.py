"""Repository interfaces (Repository pattern).

Services depend on these protocols, not on SQLite, so storage can be swapped
(e.g. Postgres) without touching business logic, and tests can use any backend.
"""

from __future__ import annotations

from typing import Protocol

from app.domain.models import Business, Enquiry


class BusinessRepository(Protocol):
    async def get(self, slug: str) -> Business | None: ...

    async def list_all(self) -> list[Business]: ...

    async def save(self, business: Business) -> None: ...

    async def count(self) -> int: ...


class EnquiryRepository(Protocol):
    async def get(self, enquiry_id: str) -> Enquiry | None: ...

    async def list_recent(self, limit: int = 50) -> list[Enquiry]: ...

    async def save(self, enquiry: Enquiry) -> None: ...
