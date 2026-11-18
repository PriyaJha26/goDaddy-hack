"""Web security building blocks: owner sessions, CSRF, rate limiting and security headers.

The middlewares are pure ASGI (not ``BaseHTTPMiddleware``) so they don't buffer the
streaming responses used by the MCP transport.
"""

from __future__ import annotations

import hmac
import secrets
import time
from collections import defaultdict, deque
from dataclasses import dataclass

from itsdangerous import BadSignature, URLSafeTimedSerializer
from starlette.datastructures import Headers
from starlette.types import ASGIApp, Message, Receive, Scope, Send

SESSION_COOKIE = "ofa_owner"


class LoginRequired(Exception):
    """Raised by the owner dependency; handled by redirecting to the login page."""


class CsrfFailed(Exception):
    pass


@dataclass(frozen=True, slots=True)
class OwnerSession:
    csrf_token: str


class SessionManager:
    """Signed, expiring owner session stored in an HttpOnly cookie."""

    def __init__(self, secret_key: str, max_age_seconds: int, secure: bool) -> None:
        self._serializer = URLSafeTimedSerializer(secret_key, salt="owner-session")
        self.max_age = max_age_seconds
        self.secure = secure

    def issue(self) -> tuple[str, OwnerSession]:
        session = OwnerSession(csrf_token=secrets.token_urlsafe(32))
        return self._serializer.dumps({"csrf": session.csrf_token}), session

    def load(self, cookie: str | None) -> OwnerSession | None:
        if not cookie:
            return None
        try:
            data = self._serializer.loads(cookie, max_age=self.max_age)
        except BadSignature:
            return None
        csrf = data.get("csrf") if isinstance(data, dict) else None
        return OwnerSession(csrf_token=csrf) if isinstance(csrf, str) else None


def passwords_match(candidate: str, expected: str) -> bool:
    return hmac.compare_digest(candidate.encode("utf-8"), expected.encode("utf-8"))


def verify_csrf(session: OwnerSession, submitted: str | None) -> None:
    if not submitted or not hmac.compare_digest(session.csrf_token, submitted):
        raise CsrfFailed()


class RateLimiter:
    """In-memory sliding-window limiter. Good for a single instance; use Redis when scaling out."""

    def __init__(self, clock=time.monotonic) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._clock = clock

    def allow(self, key: str, limit: int, window_seconds: float = 60.0) -> bool:
        now = self._clock()
        hits = self._hits[key]
        while hits and now - hits[0] >= window_seconds:
            hits.popleft()
        if len(hits) >= limit:
            return False
        hits.append(now)
        return True


class RateLimitMiddleware:
    """Applies a per-client limit to requests for a wrapped ASGI app (used for the MCP endpoint)."""

    def __init__(self, app: ASGIApp, limiter: RateLimiter, bucket: str, limit: int) -> None:
        self.app, self.limiter, self.bucket, self.limit = app, limiter, bucket, limit

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope.get("method") == "POST":
            client = (scope.get("client") or ("unknown", 0))[0]
            if not self.limiter.allow(f"{self.bucket}:{client}", self.limit):
                await send(
                    {
                        "type": "http.response.start",
                        "status": 429,
                        "headers": [(b"content-type", b"text/plain"), (b"retry-after", b"60")],
                    }
                )
                await send({"type": "http.response.body", "body": b"Too many requests"})
                return
        await self.app(scope, receive, send)


CONTENT_SECURITY_POLICY = (
    "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; "
    "connect-src 'self'; frame-ancestors 'none'; form-action 'self'; base-uri 'none'; object-src 'none'"
)


class SecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp, hsts: bool) -> None:
        self.app = app
        self.headers = [
            (b"x-content-type-options", b"nosniff"),
            (b"referrer-policy", b"strict-origin-when-cross-origin"),
            (b"x-frame-options", b"DENY"),
            (b"permissions-policy", b"camera=(), microphone=(), geolocation=()"),
            (b"content-security-policy", CONTENT_SECURITY_POLICY.encode()),
        ]
        if hsts:
            self.headers.append((b"strict-transport-security", b"max-age=31536000; includeSubDomains"))

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                existing = Headers(raw=message["headers"])
                extra = [(k, v) for k, v in self.headers if k.decode() not in existing]
                message["headers"] = [*message["headers"], *extra]
            await send(message)

        await self.app(scope, receive, send_with_headers)
