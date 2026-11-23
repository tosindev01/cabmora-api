from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.entities.asset import (
    Asset,
    AssetKind,
    StorageEvent,
    StorageEventKind,
    StoredObject,
)
from app.infrastructure.database import Base


class StoredObjectModel(Base):
    """One blob in the bucket. The hash is the primary key, by design."""

    __tablename__ = "stored_objects"

    content_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    byte_size: Mapped[int] = mapped_column(Integer)
    content_type: Mapped[str] = mapped_column(String(128))
    reference_count: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    def to_entity(self) -> StoredObject:
        return StoredObject(
            content_hash=self.content_hash,
            byte_size=self.byte_size,
            content_type=self.content_type,
            reference_count=self.reference_count,
            created_at=self.created_at,
        )


class AssetModel(Base):
    __tablename__ = "assets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(36), index=True)
    #: Not a foreign key with a cascade: deleting a blob must never silently
    #: take assets with it. Release goes through the reference count.
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    kind: Mapped[str] = mapped_column(String(16), index=True)
    filename: Mapped[str] = mapped_column(String(255))
    uploaded_by: Mapped[str] = mapped_column(String(36), index=True)
    derived_from: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    renditions_ready_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    rendition_attempts: Mapped[int] = mapped_column(
        # `server_default` as well as `default`: SQLite cannot add a NOT
        # NULL column to an existing table without one, so the migration
        # fails on a real database while passing on a fresh create_all.
        Integer, default=0, server_default="0"
    )
    rendition_error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Indexed: every gallery listing asks "what has been replaced" once.
    supersedes: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    released_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    #: Nullable and no foreign key, matching `content_hash` above: dropping a
    #: folder must never take photographs with it. Unfiling is an explicit
    #: step in `ManageFolders.delete`, not a cascade nobody can see.
    #: Indexed because the admin gallery filters by it on every view.
    folder_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    def to_entity(self) -> Asset:
        return Asset(
            id=UUID(self.id),
            project_id=UUID(self.project_id),
            content_hash=self.content_hash,
            kind=AssetKind(self.kind),
            filename=self.filename,
            uploaded_by=UUID(self.uploaded_by),
            derived_from=UUID(self.derived_from) if self.derived_from else None,
            renditions_ready_at=self.renditions_ready_at,
            rendition_attempts=self.rendition_attempts or 0,
            rendition_error=self.rendition_error,
            supersedes=UUID(self.supersedes) if self.supersedes else None,
            folder_id=UUID(self.folder_id) if self.folder_id else None,
            released_at=self.released_at,
            created_at=self.created_at,
        )


class StorageEventModel(Base):
    """Append-only. Nothing in the codebase may UPDATE or DELETE this table."""

    __tablename__ = "storage_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    account_id: Mapped[str] = mapped_column(String(36), index=True)
    asset_id: Mapped[str] = mapped_column(String(36), index=True)
    kind: Mapped[str] = mapped_column(String(16))
    byte_size: Mapped[int] = mapped_column(Integer)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)

    def to_entity(self) -> StorageEvent:
        return StorageEvent(
            id=UUID(self.id),
            account_id=UUID(self.account_id),
            asset_id=UUID(self.asset_id),
            kind=StorageEventKind(self.kind),
            byte_size=self.byte_size,
            occurred_at=self.occurred_at,
        )
