from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, Float, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.entities.comment import Comment, CommentKind
from app.infrastructure.database import Base


class CommentModel(Base):
    __tablename__ = "comments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(36), index=True)
    #: Null for feedback about the project rather than one photograph.
    asset_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    parent_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    # Fractions of the photograph's width and height — see the entity for why
    # not pixels. Nullable: most feedback is about the picture, not a spot.
    point_x: Mapped[float | None] = mapped_column(Float, nullable=True)
    point_y: Mapped[float | None] = mapped_column(Float, nullable=True)
    author_id: Mapped[str] = mapped_column(String(36), index=True)
    body: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(16), index=True)
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    resolved_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)

    def to_entity(self) -> Comment:
        return Comment(
            id=UUID(self.id),
            project_id=UUID(self.project_id),
            asset_id=UUID(self.asset_id) if self.asset_id else None,
            parent_id=UUID(self.parent_id) if self.parent_id else None,
            point_x=self.point_x,
            point_y=self.point_y,
            author_id=UUID(self.author_id),
            body=self.body,
            kind=CommentKind(self.kind),
            resolved_at=self.resolved_at,
            resolved_by=UUID(self.resolved_by) if self.resolved_by else None,
            created_at=self.created_at,
        )
