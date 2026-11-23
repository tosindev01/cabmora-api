from abc import ABC, abstractmethod
from uuid import UUID

from app.domain.entities.password_reset import PasswordResetToken


class PasswordResetRepository(ABC):
    @abstractmethod
    async def add(self, token: PasswordResetToken) -> PasswordResetToken: ...

    @abstractmethod
    async def get_by_hash(self, token_hash: str) -> PasswordResetToken | None:
        """Looked up by hash, never by plaintext — the plaintext is not stored."""

    @abstractmethod
    async def mark_used(self, token: PasswordResetToken) -> None: ...

    @abstractmethod
    async def invalidate_outstanding(self, user_id: UUID) -> None:
        """Spend every other live link for this account.

        Asking again should retire the previous email: otherwise every reset
        anyone ever requested stays usable for its full hour, and a link
        forwarded or left in a shared inbox keeps working after the person
        has already regained access.
        """
