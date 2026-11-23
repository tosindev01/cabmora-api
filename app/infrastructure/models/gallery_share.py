from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.entities.gallery_share import GalleryShare
from app.infrastructure.database import Base


class GalleryShareModel(Base):
    __tablename__ = "gallery_shares"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(36), index=True)
    #: Unique and indexed: every public request is a lookup on this column,
    #: and two links hashing the same would mean a collision in a secret.
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    created_by: Mapped[str] = mapped_column(String(36))
    label: Mapped[str] = mapped_column(String(80), default="")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_viewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    views: Mapped[int] = mapped_column(Integer, default=0)
    #: Whether only some photographs are behind this link. The chosen ids
    #: live in `gallery_share_assets`; see the entity for why the flag is
    #: stored rather than derived from whether any rows exist.
    selective: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    def to_entity(self) -> GalleryShare:
        # `asset_ids` is attached by the repository, which loads them for
        # every share on the page in one query — the same shape as
        # `AccessGroupModel` and its permissions.
        return GalleryShare(
            id=UUID(self.id),
            project_id=UUID(self.project_id),
            token_hash=self.token_hash,
            created_by=UUID(self.created_by),
            label=self.label,
            expires_at=self.expires_at,
            revoked_at=self.revoked_at,
            last_viewed_at=self.last_viewed_at,
            views=self.views,
            selective=self.selective,
            created_at=self.created_at,
        )

    @classmethod
    def from_entity(cls, share: GalleryShare) -> "GalleryShareModel":
        return cls(
            id=str(share.id),
            project_id=str(share.project_id),
            token_hash=share.token_hash,
            created_by=str(share.created_by),
            label=share.label,
            expires_at=share.expires_at,
            revoked_at=share.revoked_at,
            last_viewed_at=share.last_viewed_at,
            views=share.views,
            selective=share.selective,
            created_at=share.created_at,
        )


class GalleryShareAssetModel(Base):
    """Which photographs one link shows.

    A table rather than a JSON column on the share, so that deleting a
    photograph can take its membership with it and nothing is left pointing
    at an asset that no longer exists.

    No foreign key, matching `user_groups` and `access_group_permissions`:
    this schema does not declare them, and a half-applied convention is
    worse than a consistent absence. The repository deletes these rows with
    the share.
    """

    __tablename__ = "gallery_share_assets"

    share_id: Mapped[str] = mapped_column(String(36), primary_key=True, index=True)
    #: The **original's** id, never a preview's — that is the id the gallery
    #: lists and the one supersession is expressed against.
    asset_id: Mapped[str] = mapped_column(String(36), primary_key=True, index=True)
