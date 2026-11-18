"""Loads demo businesses into an empty database so the directory isn't blank on first run."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

from app.domain.models import Business
from app.repositories.base import BusinessRepository

logger = logging.getLogger(__name__)

SEED_FILE = Path(__file__).parent / "seed_data.json"


async def seed_if_empty(repo: BusinessRepository, path: Path = SEED_FILE) -> int:
    if await repo.count() > 0:
        return 0
    raw = await asyncio.to_thread(path.read_text, encoding="utf-8")
    businesses = [Business.model_validate(item) for item in json.loads(raw)]
    for business in businesses:
        await repo.save(business)
    logger.info("Seeded %d demo businesses", len(businesses))
    return len(businesses)
