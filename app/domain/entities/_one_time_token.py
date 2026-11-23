"""The mechanism behind every emailed one-time link.

Invites and password resets differ in intent and in how long they may live,
but not in how the secret is made, stored or checked. That part lives here.

They stay **separate types over separate tables** on purpose. A seven-day
invite that could be spent at the password-reset endpoint would hand whoever
held it a week-long window on an account meant to get an hour — and a shared
table with a `purpose` column makes that a check somebody can forget rather
than something the schema makes impossible.
"""

import hashlib
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import UUID, uuid4

#: Long enough that guessing is not a strategy.
TOKEN_BYTES = 32


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_token() -> tuple[str, str]:
    """A link-safe secret and the hash to store.

    The plaintext is returned once and never again — the same reason a
    password is not readable after it is set.
    """
    token = secrets.token_urlsafe(TOKEN_BYTES)
    return token, hash_token(token)


@dataclass
class OneTimeToken:
    """Only the *hash* is stored.

    One of these links is a credential: a readable column would be a list of
    working ones, and anyone with database read access could take over every
    account with an outstanding link.
    """

    user_id: UUID
    token_hash: str
    expires_at: datetime
    used_at: datetime | None = None
    id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @staticmethod
    def hash_of(token: str) -> str:
        return hash_token(token)

    def is_usable(self, now: datetime | None = None) -> bool:
        now = now or datetime.now(timezone.utc)
        expires = self.expires_at
        # SQLite hands back naive datetimes; compare like with like rather
        # than raising deep inside a login attempt.
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        return self.used_at is None and expires > now
