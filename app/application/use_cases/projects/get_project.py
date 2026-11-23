from uuid import UUID

from app.core.exceptions import EntityNotFoundError, PermissionDeniedError
from app.domain.entities.project import Project
from app.domain.entities.project_event import ProjectEvent
from app.domain.entities.user import User
from app.domain.repositories.project_repository import ProjectRepository


class GetProject:
    def __init__(self, projects: ProjectRepository) -> None:
        self._projects = projects

    async def execute(self, project_id: UUID, actor: User) -> tuple[Project, list[ProjectEvent]]:
        project = await self._projects.get_by_id(project_id)
        if project is None:
            raise EntityNotFoundError("Project not found")
        if not project.is_visible_to(actor):
            # 403 rather than 404: the row-level check is the point, and a
            # customer guessing another customer's id learns nothing either way.
            raise PermissionDeniedError("You do not have access to this project.")
        return project, await self._projects.list_events(project_id)
