"""Reading your own feed, and clearing it.

Every one of these takes the actor and derives the scope from them. None takes
a `user_id` — a notification feed is the one screen where an id in a query
string is an authorisation bug rather than a convenience.
"""

from dataclasses import dataclass
from uuid import UUID

from app.domain.entities.notification import Notification, NotificationTopic
from app.domain.entities.user import User
from app.domain.repositories.notification_repository import NotificationRepository


@dataclass
class Feed:
    items: list[Notification]
    #: Across the whole feed, not just this page. The badge has to be right
    #: when the dropdown is showing twenty of eighty.
    unread: int


class ListNotifications:
    def __init__(self, notifications: NotificationRepository) -> None:
        self._notifications = notifications

    async def execute(
        self,
        *,
        actor: User,
        topic: NotificationTopic | None = None,
        unread_only: bool = False,
        limit: int = 30,
        offset: int = 0,
    ) -> Feed:
        items = await self._notifications.list_for_user(
            actor.id,
            topic=topic,
            unread_only=unread_only,
            limit=limit,
            offset=offset,
        )
        return Feed(items=items, unread=await self._notifications.count_unread(actor.id))


class CountUnread:
    """Just the number, for the badge.

    Its own endpoint rather than making every page load the feed: the badge sits
    in the topbar of every portal screen, and a count is one indexed COUNT while
    a feed is rows, bodies and a sort.
    """

    def __init__(self, notifications: NotificationRepository) -> None:
        self._notifications = notifications

    async def execute(self, *, actor: User) -> int:
        return await self._notifications.count_unread(actor.id)


class MarkNotificationsRead:
    def __init__(self, notifications: NotificationRepository) -> None:
        self._notifications = notifications

    async def execute(
        self, *, actor: User, notification_ids: list[UUID] | None = None
    ) -> int:
        """Some, or all of them.

        An empty list and `None` mean different things on purpose: `None` is
        "clear everything", an empty list is "clear these nothing" and changes
        nothing. Collapsing the two would make a client that sends an
        accidentally-empty selection wipe the whole feed.
        """
        if notification_ids is None:
            return await self._notifications.mark_all_read(actor.id)
        return await self._notifications.mark_read(actor.id, notification_ids)
