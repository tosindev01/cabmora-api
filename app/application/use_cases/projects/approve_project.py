"""The client accepts the work.

Separate from `ChangeProjectStage`, which is manager-only by design: letting a
customer drive the stage machine would hand them shooting, editing and closing
as well. Approval is the one move that belongs to whoever commissioned the
work, and it is the only stage change they can make.
"""

from uuid import UUID

from app.core.exceptions import EntityNotFoundError, PermissionDeniedError
from app.domain.entities.project import Project
from app.domain.entities.project_event import ProjectEvent, ProjectEventKind
from app.domain.entities.user import User
from app.application.use_cases.notifications.notifier import Notifier
from app.domain.repositories.project_repository import ProjectRepository


class ApproveProject:
    def __init__(self, projects: ProjectRepository, notifier: Notifier) -> None:
        self._projects = projects
        self._notifier = notifier

    async def execute(self, project_id: UUID, actor: User) -> Project:
        project = await self._projects.get_by_id(project_id)
        if project is None:
            raise EntityNotFoundError("Project not found")

        # Whoever commissioned it, and nobody else. An admin approving on the
        # client's behalf would make the audit trail say the client signed off
        # when they did not — which is the one question this record exists to
        # answer.
        if project.customer_id is None or project.customer_id != actor.id:
            raise PermissionDeniedError("Only the client can approve this work.")

        # Raises if the work is not with them for review.
        project.approve(actor.id)

        saved = await self._projects.update(
            project,
            ProjectEvent(
                project_id=project.id,
                kind=ProjectEventKind.APPROVED,
                actor_id=actor.id,
            ),
        )
        # The office, not the client: they are the one who just pressed it. A
        # sign-off is the moment delivery can proceed, and until now the only
        # way to learn it had happened was to open the project.
        await self._notifier.project_approved(
            project_id=saved.id,
            project_title=saved.title,
            customer_name=actor.full_name,
        )
        return saved
