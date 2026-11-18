"""Application factory (Factory pattern): builds a fully wired FastAPI app from settings.

Run locally:   uvicorn app.main:app_factory --factory --reload
In Docker:     see Dockerfile / docker-compose.yml
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from mcp.server.transport_security import TransportSecuritySettings

from app.config import Settings, get_settings
from app.container import Container, build_container
from app.domain.errors import (
    ConflictError,
    DomainError,
    ExternalServiceError,
    NotFoundError,
    ValidationFailed,
)
from app.seed import seed_if_empty
from app.web import routes_owner, routes_public, routes_try
from app.web.deps import render
from app.web.security import (
    CsrfFailed,
    LoginRequired,
    RateLimiter,
    RateLimitMiddleware,
    SecurityHeadersMiddleware,
    SessionManager,
)

logger = logging.getLogger(__name__)

_STATUS_FOR: dict[type[DomainError], int] = {
    NotFoundError: 404,
    ValidationFailed: 422,
    ConflictError: 409,
    ExternalServiceError: 503,
}


def _wants_json(request: Request) -> bool:
    return request.url.path.startswith("/api/") or "application/json" in request.headers.get("accept", "")


def _error_response(request: Request, status: int, message: str):
    if _wants_json(request):
        return JSONResponse({"error": message}, status_code=status)
    return render(request, "message.html", status_code=status, title="Something went wrong", body=message)


def _mcp_transport_security(settings: Settings) -> TransportSecuritySettings:
    """DNS-rebinding protection: only accept requests addressed to our own host."""
    host = settings.public_host
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=[host, f"{host}:*", "localhost:*", "127.0.0.1:*", "testserver"],
        allowed_origins=[settings.public_base_url.rstrip("/"), "http://localhost:*", "http://127.0.0.1:*"],
    )


def create_app(settings: Settings | None = None, container: Container | None = None) -> FastAPI:
    settings = settings or get_settings()
    if settings.use_system_truststore:  # corporate TLS-inspecting proxies (local dev only)
        import truststore

        truststore.inject_into_ssl()
    container = container or build_container(settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        await container.db.migrate()
        if settings.seed_demo_data:
            await seed_if_empty(container.businesses)
        async with container.mcp.session_manager.run():
            yield

    app = FastAPI(
        title=settings.site_name,
        lifespan=lifespan,
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None,
        openapi_url=None if settings.is_production else "/openapi.json",
    )
    app.state.container = container
    app.state.limiter = RateLimiter()
    app.state.sessions = SessionManager(
        settings.secret_key.get_secret_value(),
        settings.session_max_age_seconds,
        secure=settings.public_base_url.startswith("https://"),
    )

    @app.exception_handler(DomainError)
    async def domain_error(request: Request, exc: DomainError):
        return _error_response(request, _STATUS_FOR.get(type(exc), 400), str(exc))

    @app.exception_handler(LoginRequired)
    async def login_required(request: Request, _: LoginRequired):
        return RedirectResponse("/owner/login", status_code=303)

    @app.exception_handler(CsrfFailed)
    async def csrf_failed(request: Request, _: CsrfFailed):
        return _error_response(request, 403, "Your session expired. Please reload the page and try again.")

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException):
        return _error_response(request, exc.status_code, str(exc.detail))

    @app.exception_handler(RequestValidationError)
    async def request_invalid(request: Request, exc: RequestValidationError):
        fields = sorted({str(e["loc"][-1]) for e in exc.errors()})
        return _error_response(request, 422, f"Please check these fields: {', '.join(fields)}")

    app.mount("/static", StaticFiles(directory=Path(__file__).parent / "web" / "static"), name="static")
    app.include_router(routes_public.router)
    app.include_router(routes_owner.router)
    app.include_router(routes_try.router)

    # The MCP endpoint lives at /mcp. Mounted last so the routes above take precedence.
    mcp_app = container.mcp.streamable_http_app(
        streamable_http_path="/mcp",
        stateless_http=True,
        json_response=True,
        transport_security=_mcp_transport_security(settings),
    )
    app.mount("/", RateLimitMiddleware(mcp_app, app.state.limiter, bucket="mcp", limit=60))

    app.add_middleware(SecurityHeadersMiddleware, hsts=settings.public_base_url.startswith("https://"))
    return app


def app_factory() -> FastAPI:
    """Entry point for ``uvicorn app.main:app_factory --factory``."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    return create_app()
