from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.entities.notification import Notification, NotificationTopic
from app.infrastructure.database import Base


class NotificationModel(Base):
    __tablename__ = "notifications"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), index=True)
    topic: Mapped[str] = mapped_column(String(20))
    title: Mapped[str] = mapped_column(String(160))
    #: Text rather than a bounded String: the entity already caps it, and a
    #: quoted message that grew past the column would fail the write rather
    #: than the validation, which is the wrong place to find out.
    body: Mapped[str] = mapped_column(Text, default="")
    url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        # The feed query: one person's notices, newest first. A composite in
        # this order lets the index satisfy both the filter and the sort, so
        # opening the bell does not sort a growing table on every click.
        Index("ix_notifications_user_created", "user_id", "created_at"),
        # The badge: unread for one person. Counted on every page load of every
        # portal screen, which makes it the hottest query of the three.
        Index("ix_notifications_user_read", "user_id", "read_at"),
    )

    def to_entity(self) -> Notification:
        return Notification(
            id=UUID(self.id),
            user_id=UUID(self.user_id),
            topic=NotificationTopic(self.topic),
            title=self.title,
            body=self.body or "",
            url=self.url,
            read_at=self.read_at,
            created_at=self.created_at,
        )

    @classmethod
    def from_entity(cls, notification: Notification) -> "NotificationModel":
        return cls(
            id=str(notification.id),
            user_id=str(notification.user_id),
            topic=notification.topic.value,
            title=notification.title,
            body=notification.body,
            url=notification.url,
            read_at=notification.read_at,
            created_at=notification.created_at,
        )
