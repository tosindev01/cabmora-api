from uuid import UUID

from app.core.exceptions import EntityNotFoundError, ValidationError
from app.domain.entities.project import Project
from app.domain.entities.project_event import ProjectEvent, ProjectEventKind
from app.domain.entities.user import UserRole
from app.domain.repositories.project_repository import ProjectRepository
from app.domain.repositories.user_repository import UserRepository


class CreateProject:
    def __init__(self, projects: ProjectRepository, users: UserRepository) -> None:
        self._projects = projects
        self._users = users

    async def execute(self, actor_id: UUID, **fields) -> Project:
        # A project may be created before the client exists — booked from an
        # enquiry, with the account provisioned separately. When a customer *is*
        # given, it must be a real customer: a project hung on an admin or a
        # creator by mistake shows up in the wrong person's portal and is
        # invisible to the person who paid for it.
        customer_id = fields.get("customer_id")
        if customer_id is not None:
            customer = await self._users.get_by_id(customer_id)
            if customer is None:
                raise EntityNotFoundError("Customer not found")
            if customer.role is not UserRole.CUSTOMER:
                raise ValidationError(
                    "A project's customer must be a customer account."
                )

        creator_id = fields.get("creator_id")
        if creator_id is not None:
            creator = await self._users.get_by_id(creator_id)
            if creator is None or creator.role is not UserRole.CREATOR:
                raise ValidationError("Assigned creator must be a creator account.")

        project = Project(**fields)
        return await self._projects.add(
            project,
            ProjectEvent(
                project_id=project.id,
                kind=ProjectEventKind.CREATED,
                actor_id=actor_id,
                payload={"title": project.title},
            ),
        )
