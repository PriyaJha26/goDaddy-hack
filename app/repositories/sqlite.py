"""SQLite implementations of the repositories.

Aggregates are stored as validated JSON documents, which keeps the schema simple
while Pydantic guarantees integrity on every read and write. Schema changes are
applied as ordered migrations tracked with ``PRAGMA user_version``.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import aiosqlite

from app.domain.models import Business, Enquiry

MIGRATIONS: list[str] = [
    """
    CREATE TABLE businesses (
        slug TEXT PRIMARY KEY,
        doc TEXT NOT NULL,
        created_at TEXT NOT NULL
    );
    CREATE TABLE enquiries (
        id TEXT PRIMARY KEY,
        business_slug TEXT NOT NULL REFERENCES businesses(slug),
        doc TEXT NOT NULL,
        created_at TEXT NOT NULL
    );
    CREATE INDEX idx_enquiries_created ON enquiries(created_at DESC);
    """,
]


class Database:
    """Owns the database location and applies migrations."""

    def __init__(self, path: Path | str) -> None:
        self._path = str(path)

    @asynccontextmanager
    async def connect(self) -> AsyncIterator[aiosqlite.Connection]:
        async with aiosqlite.connect(self._path) as conn:
            await conn.execute("PRAGMA foreign_keys = ON")
            yield conn

    async def migrate(self) -> None:
        if self._path != ":memory:":
            Path(self._path).parent.mkdir(parents=True, exist_ok=True)
        async with self.connect() as conn:
            await conn.execute("PRAGMA journal_mode = WAL")
            (version,) = await (await conn.execute("PRAGMA user_version")).fetchone()
            for index, script in enumerate(MIGRATIONS[version:], start=version + 1):
                await conn.executescript(script)
                await conn.execute(f"PRAGMA user_version = {int(index)}")
            await conn.commit()


class SqliteBusinessRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def get(self, slug: str) -> Business | None:
        async with self._db.connect() as conn:
            row = await (await conn.execute("SELECT doc FROM businesses WHERE slug = ?", (slug,))).fetchone()
        return Business.model_validate_json(row[0]) if row else None

    async def list_all(self) -> list[Business]:
        async with self._db.connect() as conn:
            rows = await (await conn.execute("SELECT doc FROM businesses ORDER BY created_at")).fetchall()
        return [Business.model_validate_json(r[0]) for r in rows]

    async def save(self, business: Business) -> None:
        async with self._db.connect() as conn:
            await conn.execute(
                "INSERT INTO businesses (slug, doc, created_at) VALUES (?, ?, ?) "
                "ON CONFLICT(slug) DO UPDATE SET doc = excluded.doc",
                (business.slug, business.model_dump_json(), business.created_at.isoformat()),
            )
            await conn.commit()

    async def count(self) -> int:
        async with self._db.connect() as conn:
            (n,) = await (await conn.execute("SELECT COUNT(*) FROM businesses")).fetchone()
        return int(n)


class SqliteEnquiryRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def get(self, enquiry_id: str) -> Enquiry | None:
        async with self._db.connect() as conn:
            row = await (await conn.execute("SELECT doc FROM enquiries WHERE id = ?", (enquiry_id,))).fetchone()
        return Enquiry.model_validate_json(row[0]) if row else None

    async def list_recent(self, limit: int = 50) -> list[Enquiry]:
        async with self._db.connect() as conn:
            rows = await (
                await conn.execute("SELECT doc FROM enquiries ORDER BY created_at DESC LIMIT ?", (limit,))
            ).fetchall()
        return [Enquiry.model_validate_json(r[0]) for r in rows]

    async def save(self, enquiry: Enquiry) -> None:
        async with self._db.connect() as conn:
            await conn.execute(
                "INSERT INTO enquiries (id, business_slug, doc, created_at) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET doc = excluded.doc",
                (enquiry.id, enquiry.business_slug, enquiry.model_dump_json(), enquiry.created_at.isoformat()),
            )
            await conn.commit()
