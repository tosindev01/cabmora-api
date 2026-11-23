from abc import ABC, abstractmethod

from app.domain.entities.invite import InviteToken


class InviteRepository(ABC):
    @abstractmethod
    async def add(self, invite: InviteToken) -> InviteToken: ...

    @abstractmethod
    async def get_by_hash(self, token_hash: str) -> InviteToken | None:
        """Looked up by hash, never by plaintext — the plaintext is not stored."""

    @abstractmethod
    async def mark_used(self, invite: InviteToken) -> None: ...
