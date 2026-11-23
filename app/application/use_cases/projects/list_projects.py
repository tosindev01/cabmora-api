from dataclasses import dataclass
from datetime import date
from uuid import UUID

from app.domain.entities.project import Project, ProjectStage
from app.domain.entities.user import User, UserRole
from app.domain.repositories.project_repository import ProjectRepository

DEFAULT_PAGE_SIZE = 30


@dataclass
class ProjectPage:
    items: list[Project]
    total: int
    limit: int
    offset: int


class ListProjects:
    def __init__(self, projects: ProjectRepository) -> None:
        self._projects = projects

    async def execute(
        self,
        actor: User,
        limit: int = DEFAULT_PAGE_SIZE,
        offset: int = 0,
        stage: ProjectStage | None = None,
        customer_id: UUID | None = None,
        creator_id: UUID | None = None,
        search: str | None = None,
        access_for: UUID | None = None,
        event_from: date | None = None,
        event_to: date | None = None,
        due_within_days: int | None = None,
    ) -> ProjectPage:
        # Scope decided here, from who is asking, rather than in the router.
        # A gate that let somebody reach this endpoint has said nothing about
        # which rows they may read, and a list that forgets is the leak that
        # matters: it hands over every client's project title and customer
        # to somebody who cannot open any of them.
        #
        # An administrator may pass `access_for` to ask what somebody else can
        # open — that is the oversight question. A coordinator's is overwritten
        # with their own id rather than rejected: asking about a colleague is
        # not an attack, and answering with their own list is both safe and
        # the only honest answer to "which of these may I see".
        if actor.role is UserRole.COORDINATOR:
            access_for = actor.id

        items = await self._projects.list_all(
            limit=limit, offset=offset, stage=stage,
            customer_id=customer_id, creator_id=creator_id, search=search,
            event_from=event_from, event_to=event_to,
            due_within_days=due_within_days,
            access_for=access_for,
        )
        total = await self._projects.count_all(
            stage=stage, customer_id=customer_id, creator_id=creator_id,
            search=search, access_for=access_for,
            event_from=event_from, event_to=event_to,
            due_within_days=due_within_days,
        )
        return ProjectPage(items=items, total=total, limit=limit, offset=offset)
