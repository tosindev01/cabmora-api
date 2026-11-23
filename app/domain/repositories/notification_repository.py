from abc import ABC, abstractmethod
from collections.abc import Sequence
from uuid import UUID

from app.domain.entities.notification import Notification, NotificationTopic


class NotificationRepository(ABC):
    @abstractmethod
    async def add_many(self, notifications: Sequence[Notification]) -> None:
        """Record a fan-out in one write.

        Plural rather than singular because the common case is plural: an
        enquiry notifies every member of staff, and one insert per admin inside
        a loop is a round trip per admin on the critical path of a public form
        submission.

        An empty sequence is a no-op, not an error — "tell everyone" with
        nobody to tell is a quiet morning, not a bug.
        """

    @abstractmethod
    async def list_for_user(
        self,
        user_id: UUID,
        *,
        topic: NotificationTopic | None = None,
        unread_only: bool = False,
        limit: int = 30,
        offset: int = 0,
    ) -> list[Notification]:
        """Newest first. Scoped to one account by argument, never by filter —
        a `user_id` the caller can choose is how one person reads another's
        feed."""

    @abstractmethod
    async def count_unread(self, user_id: UUID) -> int:
        """The badge. Counted in the database rather than by measuring a page
        of rows, which would cap the badge at the page size."""

    @abstractmethod
    async def mark_read(self, user_id: UUID, notification_ids: Sequence[UUID]) -> int:
        """Mark specific notices read, returning how many changed.

        `user_id` is part of the WHERE clause, not a check beforehand: a single
        statement that cannot match somebody else's row is safer than a read,
        a comparison and a write that can race.
        """

    @abstractmethod
    async def mark_all_read(self, user_id: UUID) -> int:
        """Clear the badge. Returns how many were still unread."""
