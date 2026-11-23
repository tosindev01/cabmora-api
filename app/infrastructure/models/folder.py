from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.entities.folder import Folder
from app.infrastructure.database import Base


class FolderModel(Base):
    __tablename__ = "folders"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(36), index=True)
    name: Mapped[str] = mapped_column(String(60))
    position: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    def to_entity(self) -> Folder:
        # The count is attached by the repository, which loads it for the
        # whole project in one grouped query rather than per folder.
        return Folder(
            id=UUID(self.id),
            project_id=UUID(self.project_id),
            name=self.name,
            position=self.position or 0,
            created_at=self.created_at,
        )
