from uuid import UUID

from app.core.exceptions import (
    EntityNotFoundError,
    PermissionDeniedError,
    ValidationError,
)
from app.domain.entities.project import Project
from app.domain.entities.project_event import ProjectEvent, ProjectEventKind
from app.domain.entities.user import User, UserRole
from app.domain.repositories.user_repository import UserRepository
from app.domain.repositories.project_repository import ProjectRepository

#: Changing any of these is worth a line in the timeline — they alter what the
#: customer can see and when they can have it.
SETTING_FIELDS = {
    "watermark_policy",
    "release_mode",
    "require_approval_before_delivery",
    "require_payment_before_delivery",
    "allow_client_sharing",
    "allow_downloads",
    # Money, recorded for the same reason the settings are: the first time a
    # client asks why their invoice says what it says, "who changed the price,
    # and when" is the question — and before this neither was written down.
    "price_minor",
    "currency",
}


class UpdateProject:
    def __init__(self, projects: ProjectRepository, users: UserRepository) -> None:
        self._projects = projects
        self._users = users

    async def execute(self, project_id: UUID, actor: User, changes: dict) -> Project:
        project = await self._projects.get_by_id(project_id)
        if project is None:
            raise EntityNotFoundError("Project not found")
        if not project.is_managed_by(actor):
            raise PermissionDeniedError("You cannot manage this project.")

        # A customer may be attached to a project that has none — booked from
        # an enquiry, account provisioned afterwards. Moving an *existing*
        # customer to someone else is refused: their media, comments and
        # invoices would silently go with it.
        if "customer_id" in changes and changes["customer_id"] is not None:
            if project.customer_id is not None and project.customer_id != changes["customer_id"]:
                raise ValidationError(
                    "A project cannot be moved to a different customer."
                )
            customer = await self._users.get_by_id(changes["customer_id"])
            if customer is None:
                raise EntityNotFoundError("Customer not found")
            if customer.role is not UserRole.CUSTOMER:
                raise ValidationError(
                    "A project's customer must be a customer account."
                )

        for name, value in changes.items():
            setattr(project, name, value)

        # `stage` is not settable here on purpose — it goes through
        # ChangeProjectStage so the transition rules cannot be bypassed by a
        # PATCH that happens to include the field.
        touched = SETTING_FIELDS & changes.keys()
        event = (
            ProjectEvent(
                project_id=project.id,
                kind=ProjectEventKind.SETTINGS_CHANGED,
                actor_id=actor.id,
                payload={
                    key: getattr(value, "value", value)
                    for key, value in changes.items()
                    if key in touched
                },
            )
            if touched
            else None
        )
        return await self._projects.update(project, event)
