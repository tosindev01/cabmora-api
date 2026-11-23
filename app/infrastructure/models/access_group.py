from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.entities.access_group import AccessGroup
from app.infrastructure.database import Base


class AccessGroupModel(Base):
    __tablename__ = "access_groups"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(60), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    def to_entity(self) -> AccessGroup:
        # Permissions and the member count are attached by the repository,
        # which loads them for the whole page in one query each.
        return AccessGroup(
            id=UUID(self.id), name=self.name, created_at=self.created_at
        )


class AccessGroupPermissionModel(Base):
    __tablename__ = "access_group_permissions"

    group_id: Mapped[str] = mapped_column(String(36), primary_key=True, index=True)
    permission: Mapped[str] = mapped_column(String(40), primary_key=True)


class UserGroupModel(Base):
    """Who is in which group."""

    __tablename__ = "user_groups"

    user_id: Mapped[str] = mapped_column(String(36), primary_key=True, index=True)
    group_id: Mapped[str] = mapped_column(String(36), primary_key=True, index=True)
