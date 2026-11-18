"""'Try it as an AI assistant' demo: runs the shopper agent against our own MCP server."""

from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from app.domain.errors import ExternalServiceError
from app.web.deps import ContainerDep, rate_limited, render

router = APIRouter()


class TryRequest(BaseModel):
    message: str = Field(min_length=3, max_length=600)


@router.get("/try")
async def try_page(request: Request, container: ContainerDep):
    return render(request, "try.html", agent_available=container.shopper is not None)


@router.post("/api/try", dependencies=[rate_limited("try", per_minute=4)])
async def try_agent(body: TryRequest, container: ContainerDep) -> dict:
    if container.shopper is None:
        raise ExternalServiceError("The demo assistant needs ANTHROPIC_API_KEY to be configured.")
    run = await container.shopper.run(body.message)
    return {"final_answer": run.final_answer, "steps": [asdict(s) for s in run.steps]}
