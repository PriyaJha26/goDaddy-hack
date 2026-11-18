import pytest
from pydantic import SecretStr, ValidationError

from app.config import Settings
from app.web.security import (
    CsrfFailed,
    OwnerSession,
    RateLimiter,
    SessionManager,
    passwords_match,
    verify_csrf,
)


def test_session_round_trip_and_tamper_detection() -> None:
    sessions = SessionManager("k" * 40, max_age_seconds=60, secure=True)
    token, session = sessions.issue()
    assert sessions.load(token) == session
    assert sessions.load(token[:-2] + "xx") is None
    assert sessions.load(None) is None
    assert SessionManager("other" * 10, 60, True).load(token) is None


def test_csrf_verification() -> None:
    session = OwnerSession(csrf_token="abc")
    verify_csrf(session, "abc")
    for bad in (None, "", "abd"):
        with pytest.raises(CsrfFailed):
            verify_csrf(session, bad)


def test_passwords_match() -> None:
    assert passwords_match("secret", "secret")
    assert not passwords_match("secret", "Secret")


def test_rate_limiter_sliding_window() -> None:
    now = [0.0]
    limiter = RateLimiter(clock=lambda: now[0])
    assert all(limiter.allow("k", limit=3) for _ in range(3))
    assert not limiter.allow("k", limit=3)
    assert limiter.allow("other", limit=3)  # keys are independent
    now[0] = 60.0
    assert limiter.allow("k", limit=3)


def test_production_refuses_default_secrets() -> None:
    with pytest.raises(ValidationError, match="SECRET_KEY"):
        Settings(_env_file=None, environment="production")
    with pytest.raises(ValidationError, match="32 characters"):
        Settings(
            _env_file=None,
            environment="production",
            secret_key=SecretStr("short"),
            owner_password=SecretStr("a-real-password"),
        )
    ok = Settings(
        _env_file=None,
        environment="production",
        secret_key=SecretStr("x" * 40),
        owner_password=SecretStr("a-real-password"),
    )
    assert ok.is_production
