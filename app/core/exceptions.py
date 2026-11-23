"""Domain exceptions. Raised by domain/application layers; mapped to HTTP in api layer."""


class DomainError(Exception):
    """Base class for all domain errors."""


class EntityNotFoundError(DomainError):
    """Requested entity does not exist."""


class EntityAlreadyExistsError(DomainError):
    """Entity violates a uniqueness constraint (e.g. duplicate email)."""


class AuthenticationError(DomainError):
    """Invalid credentials or token."""


class PermissionDeniedError(DomainError):
    """Actor is not allowed to perform this action."""


class ValidationError(DomainError):
    """Business-rule validation failure (not schema validation)."""


class SchedulingUnavailableError(DomainError):
    """The calendar refused or failed, and it is not the caller's fault.

    Its sibling is `StorageUnavailableError`, for the same reason: an admin
    told "something went wrong" cannot tell a stale Google token from a clash
    they could fix themselves, so they retry the same click instead of asking
    anyone to look.
    """


class StorageUnavailableError(DomainError):
    """The object store refused or failed, and it is not the caller's fault.

    Kept apart from `ValidationError` on purpose. An upload that R2 would not
    finish is not a malformed request, and telling somebody to correct their
    file when the bucket is the problem sends them to fix the wrong thing —
    the same misdirection as a download error that only ever said the link had
    expired.
    """


class ConfigurationError(DomainError):
    """The deployment is missing something the action needs.

    A 500, not a 4xx: the caller did nothing wrong and cannot fix it by
    sending different data. Separate from a bare exception so the message
    reaches the operator instead of a stack trace — "ADMIN_BASE_URL must be
    set" is actionable in a way that "NoneType has no attribute" is not.
    """


class TooManyAttemptsError(DomainError):
    """Refused for making the same failing request too often.

    Carries `retry_after` so the response can say when, rather than leaving
    the caller to guess — and so a person who genuinely forgot their password
    is told to wait rather than told they are wrong again.
    """

    def __init__(self, message: str, retry_after: int) -> None:
        super().__init__(message)
        self.retry_after = retry_after
