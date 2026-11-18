"""Domain-level exceptions. The web layer maps these to HTTP status codes."""


class DomainError(Exception):
    """Base class for expected, user-facing errors."""


class NotFoundError(DomainError):
    pass


class ValidationFailed(DomainError):
    pass


class ConflictError(DomainError):
    pass


class ExternalServiceError(DomainError):
    """A dependency (Claude, SMTP) failed or is not configured."""
