"""The review queue."""

from dataclasses import dataclass
from uuid import UUID

from app.core.exceptions import EntityNotFoundError
from app.domain.entities.creator_application import (
    ApplicationStatus,
    CreatorApplication,
)
from app.domain.repositories.creator_application_repository import (
    CreatorApplicationRepository,
)


@dataclass
class ApplicationPage:
    items: list[CreatorApplication]
    total: int


class ListCreatorApplications:
    def __init__(self, applications: CreatorApplicationRepository) -> None:
        self._applications = applications

    async def execute(
        self,
        *,
        status: ApplicationStatus | None = None,
        limit: int = 30,
        offset: int = 0,
    ) -> ApplicationPage:
        return ApplicationPage(
            items=await self._applications.list_all(
                status=status, limit=limit, offset=offset
            ),
            total=await self._applications.count_all(status=status),
        )


class GetCreatorApplication:
    def __init__(self, applications: CreatorApplicationRepository) -> None:
        self._applications = applications

    async def execute(self, application_id: UUID) -> CreatorApplication:
        application = await self._applications.get_by_id(application_id)
        if application is None:
            raise EntityNotFoundError("Application not found")
        return application
