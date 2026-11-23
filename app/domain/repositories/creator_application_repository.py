from abc import ABC, abstractmethod
from uuid import UUID

from app.domain.entities.creator_application import (
    ApplicationStatus,
    CreatorApplication,
)


class CreatorApplicationRepository(ABC):
    @abstractmethod
    async def add(self, application: CreatorApplication) -> CreatorApplication: ...

    @abstractmethod
    async def get_by_id(self, application_id: UUID) -> CreatorApplication | None: ...

    @abstractmethod
    async def get_pending_by_email(self, email: str) -> CreatorApplication | None:
        """An outstanding application from this address, if there is one.

        Only the pending one: somebody declined a year ago may reapply, and a
        studio that was approved and later left should not be blocked by their
        own history.
        """

    @abstractmethod
    async def list_all(
        self,
        *,
        status: ApplicationStatus | None = None,
        limit: int = 30,
        offset: int = 0,
    ) -> list[CreatorApplication]: ...

    @abstractmethod
    async def count_all(self, *, status: ApplicationStatus | None = None) -> int: ...

    @abstractmethod
    async def update(self, application: CreatorApplication) -> CreatorApplication: ...
