from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID

from app.domain.entities._one_time_token import OneTimeToken, new_token

#: Short on purpose. Unlike an invite, whoever asked for this is at their
#: inbox right now, and the link sits in a mailbox that may outlive their
#: interest in it by years.
DEFAULT_TTL = timedelta(hours=1)


@dataclass
class PasswordResetToken(OneTimeToken):
    """A one-time link that lets someone choose a new password on an account
    they already own."""

    @classmethod
    def issue(
        cls, user_id: UUID, ttl: timedelta = DEFAULT_TTL
    ) -> tuple["PasswordResetToken", str]:
        """Return the record to store and the plaintext token to send."""
        token, digest = new_token()
        record = cls(
            user_id=user_id,
            token_hash=digest,
            expires_at=datetime.now(timezone.utc) + ttl,
        )
        return record, token
