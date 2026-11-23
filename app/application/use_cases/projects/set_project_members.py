"""Put Cabmora people on a shoot, or take them off it.

Assigning is an administrator's act, not a coordinator's: somebody who could
add themselves to a project could reach every client in the system, which
would make the whole role decorative.
"""

from uuid import UUID

from app.core.exceptions import EntityNotFoundError, ValidationError
from app.domain.entities.project import Project
from app.domain.entities.user import UserRole
from app.domain.repositories.project_repository import ProjectRepository
from app.domain.repositories.user_repository import UserRepository


class SetProjectMembers:
    def __init__(
        self, projects: ProjectRepository, users: UserRepository
    ) -> None:
        self._projects = projects
        self._users = users

    async def execute(self, *, project_id: UUID, user_ids: list[UUID]) -> Project:
        project = await self._projects.get_by_id(project_id)
        if project is None:
            raise EntityNotFoundError("Project not found")

        found = await self._users.get_many(set(user_ids))
        missing = [str(i) for i in user_ids if i not in found]
        if missing:
            raise EntityNotFoundError(
                f"{len(missing)} of those people do not exist."
            )

        # A customer on the member list would become a manager of the project
        # they commissioned — able to release their own photographs and move
        # their own stages. The entity refuses it too; refusing here as well
        # means the console says why instead of silently doing nothing.
        wrong = [
            found[i].email for i in user_ids
            if found[i].role is UserRole.CUSTOMER
        ]
        if wrong:
            raise ValidationError(
                f"{', '.join(wrong)} cannot be put on a shoot — they are clients."
            )

        project.member_ids = await self._projects.set_members(project_id, user_ids)
        return project
