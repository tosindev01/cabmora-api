"""The bell.

One router for both frontends. The console and the customer portal ask the same
three questions — how many, which ones, mark them read — and the answer is
scoped to whoever is signed in, so there is nothing for an admin variant to do
differently.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.deps import (
    CurrentActiveUserDep,
    get_count_unread_notifications,
    get_list_notifications,
    get_mark_notifications_read,
)
from app.api.schemas.notification import (
    MarkReadRequest,
    MarkReadResponse,
    NotificationFeedResponse,
    NotificationResponse,
)
from app.application.use_cases.notifications.read import (
    CountUnread,
    ListNotifications,
    MarkNotificationsRead,
)
from app.domain.entities.notification import NotificationTopic

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("", response_model=NotificationFeedResponse)
async def list_notifications(
    actor: CurrentActiveUserDep,
    use_case: Annotated[ListNotifications, Depends(get_list_notifications)],
    topic: NotificationTopic | None = Query(default=None),
    unread_only: bool = Query(default=False),
    limit: int = Query(default=30, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> NotificationFeedResponse:
    """Your feed, newest first.

    No `user_id` parameter, by design — the scope comes from the session.
    """
    feed = await use_case.execute(
        actor=actor, topic=topic, unread_only=unread_only, limit=limit, offset=offset
    )
    return NotificationFeedResponse(
        items=[
            NotificationResponse(
                id=each.id,
                topic=each.topic,
                title=each.title,
                body=each.body,
                url=each.url,
                read_at=each.read_at,
                created_at=each.created_at,
            )
            for each in feed.items
        ],
        unread=feed.unread,
    )


@router.get("/unread-count", response_model=int)
async def unread_count(
    actor: CurrentActiveUserDep,
    use_case: Annotated[CountUnread, Depends(get_count_unread_notifications)],
) -> int:
    """Just the badge. Polled from the topbar of every portal page, so it stays
    one indexed count rather than a feed nobody is looking at."""
    return await use_case.execute(actor=actor)


@router.post("/read", response_model=MarkReadResponse)
async def mark_read(
    body: MarkReadRequest,
    actor: CurrentActiveUserDep,
    use_case: Annotated[MarkNotificationsRead, Depends(get_mark_notifications_read)],
    counter: Annotated[CountUnread, Depends(get_count_unread_notifications)],
) -> MarkReadResponse:
    """Clear some, or all.

    POST rather than PATCH on each id: opening the dropdown marks everything in
    it read, and that is one request whether it covers one row or twenty.
    """
    marked = await use_case.execute(actor=actor, notification_ids=body.notification_ids)
    return MarkReadResponse(marked=marked, unread=await counter.execute(actor=actor))
