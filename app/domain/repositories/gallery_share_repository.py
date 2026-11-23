from abc import ABC, abstractmethod
from uuid import UUID

from app.domain.entities.gallery_share import GalleryShare


class GalleryShareRepository(ABC):
    @abstractmethod
    async def add(self, share: GalleryShare) -> GalleryShare: ...

    @abstractmethod
    async def get_by_token_hash(self, token_hash: str) -> GalleryShare | None:
        """Looked up by hash, never by plaintext — the column holds no
        working links for anybody with database access to read."""

    @abstractmethod
    async def get_by_id(self, share_id: UUID) -> GalleryShare | None: ...

    @abstractmethod
    async def list_for_project(self, project_id: UUID) -> list[GalleryShare]: ...

    @abstractmethod
    async def update(self, share: GalleryShare) -> GalleryShare: ...
