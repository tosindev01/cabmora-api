from abc import ABC, abstractmethod
from uuid import UUID

from app.domain.entities.rating import Rating, ReviewStatus


class RatingRepository(ABC):
    @abstractmethod
    async def add(self, rating: Rating) -> Rating: ...

    @abstractmethod
    async def get_for_project(self, project_id: UUID) -> Rating | None:
        """One per project, so this is the whole query."""

    @abstractmethod
    async def get_by_id(self, rating_id: UUID) -> Rating | None: ...

    @abstractmethod
    async def update(self, rating: Rating) -> Rating: ...

    @abstractmethod
    async def delete(self, rating_id: UUID) -> None:
        """Remove it entirely. `hide` is the reversible one; this is not."""

    @abstractmethod
    async def list_all(
        self,
        *,
        status: ReviewStatus | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Rating]:
        """Newest first, for the moderation queue."""

    @abstractmethod
    async def count_all(self, *, status: ReviewStatus | None = None) -> int: ...

    @abstractmethod
    async def list_published(self, limit: int = 12) -> list[Rating]:
        """What the public site may show. Published *and* consented — both
        checked here so an unauthenticated endpoint cannot be the one place
        that forgets."""
