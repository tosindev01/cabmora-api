from abc import ABC, abstractmethod
from uuid import UUID

from app.domain.entities.asset import Asset, StoredObject, StorageEvent


class MediaRepository(ABC):
    @abstractmethod
    async def get_object(self, content_hash: str) -> StoredObject | None: ...

    @abstractmethod
    async def record_asset(
        self, blob: StoredObject, asset: Asset, event: StorageEvent
    ) -> Asset:
        """Claim the bytes, record the asset, log the usage — one transaction.

        Deliberately one method rather than three. Claiming a blob and then
        failing to write the asset would leave a reference count insisting
        somebody needs bytes nobody points at, and that blob could never be
        collected. A usage log that can disagree with the assets it describes
        is worse than no log at all: it cannot be audited, and it cannot be
        trusted to price against later.

        The claim is atomic within it: two uploads of identical bytes racing
        must not both believe they created the object — one inserts, the other
        increments, and both see a count that includes them.
        """

    @abstractmethod
    async def get_asset(self, asset_id: UUID) -> Asset | None: ...

    @abstractmethod
    async def update_asset(self, asset: Asset) -> Asset: ...

    @abstractmethod
    async def counts_for_projects(
        self, project_ids: list[UUID]
    ) -> dict[UUID, tuple[int, int]]:
        """`{project_id: (originals, released)}` for a page of projects.

        One query for the page rather than one per project: a list screen that
        counts photographs per card is the classic N+1, and it only becomes
        visible once the studio has enough work to be worth listing.
        """

    @abstractmethod
    async def list_project_assets(
        self, project_id: UUID, kinds: list[str] | None = None
    ) -> list[Asset]: ...

    @abstractmethod
    async def set_folder(
        self, project_id: UUID, asset_ids: list[UUID], folder_id: UUID | None
    ) -> int:
        """File a batch of photographs, or unfile them with `None`.

        Scoped to the project on purpose, and not as belt and braces: without
        it a caller holding any folder could move another project's
        photographs into it, and a client would find somebody else's shoot in
        their gallery. The project is the boundary; this enforces it in the
        one statement that does the writing.

        Returns how many rows actually moved.
        """

    @abstractmethod
    async def unfile_all(self, folder_id: UUID) -> int:
        """Empty a folder without touching a single file. Used before delete."""

    @abstractmethod
    async def remove_asset(self, asset: Asset, event: StorageEvent) -> StoredObject | None:
        """Delete the asset, release its blob, and log the bytes returned.

        Returns the blob's record so the caller can see whether it is now
        orphaned — deciding to delete from the bucket is not this layer's call.
        """

    @abstractmethod
    async def list_awaiting_renditions(self, limit: int = 20) -> list[Asset]:
        """Originals whose previews have not been made yet.

        This is the work queue. Keeping it as a query over the assets rather
        than a separate jobs table means the two can never disagree about what
        is outstanding, and the backlog is visible beside the photographs.
        """

    @abstractmethod
    async def usage_bytes(self, account_id: UUID) -> int:
        """Current usage, summed from the event log rather than stored."""
