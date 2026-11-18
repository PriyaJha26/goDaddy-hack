"""FastAPI dependencies shared by the routers."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, HTTPException, Request
from fastapi.templating import Jinja2Templates

from app.container import Container
from app.web.security import SESSION_COOKIE, LoginRequired, OwnerSession, RateLimiter, SessionManager

templates = Jinja2Templates(directory=Path(__file__).parent / "templates")


def get_container(request: Request) -> Container:
    return request.app.state.container


def get_sessions(request: Request) -> SessionManager:
    return request.app.state.sessions


def get_limiter(request: Request) -> RateLimiter:
    return request.app.state.limiter


ContainerDep = Annotated[Container, Depends(get_container)]


def require_owner(request: Request, sessions: Annotated[SessionManager, Depends(get_sessions)]) -> OwnerSession:
    session = sessions.load(request.cookies.get(SESSION_COOKIE))
    if session is None:
        raise LoginRequired()
    return session


OwnerDep = Annotated[OwnerSession, Depends(require_owner)]


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def rate_limited(bucket: str, per_minute: int | None = None):
    """Dependency factory: limit a route per client IP (defaults to RATE_LIMIT_PER_MINUTE)."""

    def dependency(request: Request, limiter: Annotated[RateLimiter, Depends(get_limiter)]) -> None:
        limit = per_minute or request.app.state.container.settings.rate_limit_per_minute
        if not limiter.allow(f"{bucket}:{client_ip(request)}", limit):
            raise HTTPException(status_code=429, detail="Too many requests. Please wait a minute and try again.")

    return Depends(dependency)


def render(request: Request, name: str, status_code: int = 200, **context: Any):
    container: Container = request.app.state.container
    base = {
        "site_name": container.settings.site_name,
        "base_url": container.settings.public_base_url.rstrip("/"),
        "claude_enabled": container.settings.claude_enabled,
    }
    return templates.TemplateResponse(request, name, {**base, **context}, status_code=status_code)
