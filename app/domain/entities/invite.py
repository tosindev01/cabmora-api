from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID

from app.domain.entities._one_time_token import OneTimeToken, new_token

#: An invite is sent because somebody made an account for a person who is not
#: waiting at their inbox. A week is the working life of that expectation.
DEFAULT_TTL = timedelta(days=7)


@dataclass
class InviteToken(OneTimeToken):
    """A one-time link that lets someone set a password on an account made for
    them."""

    @classmethod
    def issue(cls, user_id: UUID, ttl: timedelta = DEFAULT_TTL) -> tuple["InviteToken", str]:
        """Return the record to store and the plaintext token to send."""
        token, digest = new_token()
        record = cls(
            user_id=user_id,
            token_hash=digest,
            expires_at=datetime.now(timezone.utc) + ttl,
        )
        return record, token
