from abc import ABC, abstractmethod
from uuid import UUID

from app.domain.entities.comment import Comment


class CommentRepository(ABC):
    @abstractmethod
    async def add(self, comment: Comment) -> Comment: ...

    @abstractmethod
    async def get_by_id(self, comment_id: UUID) -> Comment | None: ...

    @abstractmethod
    async def update(self, comment: Comment) -> Comment: ...

    @abstractmethod
    async def list_for_project(self, project_id: UUID) -> list[Comment]:
        """Every comment on the project, oldest first — including those on its
        photographs, so one read builds the whole conversation."""

    @abstractmethod
    async def list_for_projects(
        self, project_ids: list[UUID]
    ) -> dict[UUID, list["Comment"]]:
        """Every thread on a page of projects, in one query rather than one
        per project — a client's Messages screen asks about all of theirs at
        once."""

    @abstractmethod
    async def open_counts_for_projects(self, project_ids: list[UUID]) -> dict[UUID, int]:
        """Unresolved amendments per project, for a page of them at once.

        The batch form of `count_outstanding`, which stays because a detail
        page asks about one project and should not build a list to do it.
        """
        ...

    @abstractmethod
    async def count_outstanding(self, project_id: UUID) -> int:
        """Unresolved amendments. What an admin needs before moving a stage."""
