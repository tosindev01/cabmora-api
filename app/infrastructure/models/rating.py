from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy import false as sa_false
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.entities.rating import Rating, ReviewStatus
from app.infrastructure.database import Base


class RatingModel(Base):
    __tablename__ = "ratings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    #: Unique: one rating per project, enforced by the schema rather than by
    #: everybody remembering to look first.
    project_id: Mapped[str] = mapped_column(String(36), unique=True, index=True)
    customer_id: Mapped[str] = mapped_column(String(36), index=True)
    stars: Mapped[int] = mapped_column(Integer)
    words: Mapped[str] = mapped_column(Text, default="")
    #: Consent, not a preference. Defaults off — see the entity.
    may_publish: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=sa_false()
    )
    status: Mapped[str] = mapped_column(
        String(20), default=ReviewStatus.PENDING.value, index=True
    )
    moderated_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    moderated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    def to_entity(self) -> Rating:
        return Rating(
            id=UUID(self.id),
            project_id=UUID(self.project_id),
            customer_id=UUID(self.customer_id),
            stars=self.stars,
            words=self.words,
            may_publish=self.may_publish,
            status=ReviewStatus(self.status),
            moderated_by=UUID(self.moderated_by) if self.moderated_by else None,
            moderated_at=self.moderated_at,
            created_at=self.created_at,
            updated_at=self.updated_at,
        )

    @classmethod
    def from_entity(cls, rating: Rating) -> "RatingModel":
        return cls(
            id=str(rating.id),
            project_id=str(rating.project_id),
            customer_id=str(rating.customer_id),
            stars=rating.stars,
            words=rating.words,
            may_publish=rating.may_publish,
            status=rating.status.value,
            moderated_by=str(rating.moderated_by) if rating.moderated_by else None,
            moderated_at=rating.moderated_at,
            created_at=rating.created_at,
            updated_at=rating.updated_at,
        )
