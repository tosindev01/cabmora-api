from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.domain.entities.notification import NotificationTopic


class NotificationResponse(BaseModel):
    id: UUID
    topic: NotificationTopic
    title: str
    body: str
    #: A path on the app the recipient is using, or null where there is nowhere
    #: useful to go. Never an absolute URL — see the entity.
    url: str | None
    read_at: datetime | None
    created_at: datetime


class NotificationFeedResponse(BaseModel):
    items: list[NotificationResponse]
    #: Unread across the whole feed, not just this page, so a dropdown showing
    #: twenty of eighty still badges eighty.
    unread: int


class MarkReadRequest(BaseModel):
    #: Which ones. Omit the field entirely to clear the lot — that is what the
    #: "Mark all as read" control sends. An explicit empty list changes nothing,
    #: so a client that accidentally sends no selection cannot wipe the feed.
    notification_ids: list[UUID] | None = Field(default=None, max_length=200)

    model_config = ConfigDict(extra="forbid")


class MarkReadResponse(BaseModel):
    #: How many actually changed. Already-read rows are not counted, so a second
    #: click returns 0 rather than pretending to have done something.
    marked: int
    unread: int
