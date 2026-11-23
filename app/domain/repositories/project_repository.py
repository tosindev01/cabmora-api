from abc import ABC, abstractmethod
from datetime import date
from uuid import UUID

from app.domain.entities.project import Project, ProjectStage
from app.domain.entities.project_event import ProjectEvent


class ProjectRepository(ABC):
    @abstractmethod
    async def add(self, project: Project, event: ProjectEvent) -> Project:
        """Create a project and its first event in one transaction.

        Taking the event here rather than in a second call is deliberate: a
        project that exists with no `CREATED` event is a hole in the audit
        trail, and two calls can leave exactly that behind.
        """

    @abstractmethod
    async def get_by_id(self, project_id: UUID) -> Project | None: ...

    @abstractmethod
    async def set_members(self, project_id: UUID, user_ids: list[UUID]) -> list[UUID]:
        """Replace who from Cabmora is on this shoot."""

    @abstractmethod
    async def update(self, project: Project, event: ProjectEvent | None = None) -> Project:
        """Persist changes, optionally recording what caused them."""

    @abstractmethod
    async def list_all(
        self,
        limit: int = 30,
        offset: int = 0,
        stage: ProjectStage | None = None,
        customer_id: UUID | None = None,
        creator_id: UUID | None = None,
        search: str | None = None,
        access_for: UUID | None = None,
        event_from: date | None = None,
        event_to: date | None = None,
        due_within_days: int | None = None,
    ) -> list[Project]: ...

    @abstractmethod
    async def count_all(
        self,
        stage: ProjectStage | None = None,
        customer_id: UUID | None = None,
        creator_id: UUID | None = None,
        search: str | None = None,
        access_for: UUID | None = None,
        event_from: date | None = None,
        event_to: date | None = None,
        due_within_days: int | None = None,
    ) -> int: ...

    @abstractmethod
    @abstractmethod
    async def event_types(self) -> list[str]:
        """Every category in use, alphabetically.

        Derived from the projects themselves rather than kept in a table of
        its own. `event_type` has always been free text, so the categories
        already exist — they are just not offered anywhere, which is why
        "Wedding", "wedding" and "Weddings" can all be in the data at once.

        A list computed from use needs no management screen, no migration and
        no way to get out of step: a category exists while a project uses it
        and stops being offered when none does. The cost is that a typo
        becomes a category, and renaming one means editing every project that
        carries it. Worth revisiting if that starts to bite.
        """

    @abstractmethod
    async def count_completed(self) -> int:
        """Shoots that actually happened: delivered or closed.

        Both stages, because `closed` is where a delivered job ends up once the
        paperwork is done — counting only `delivered` would make the number
        shrink over time, which is the opposite of what a "events covered"
        figure is meant to say.
        """

    @abstractmethod
    async def count_clients_served(self) -> int:
        """Distinct customers with at least one completed project.

        Not the number of customer accounts. Somebody who signed up and never
        booked is not a client served, and counting them would make a public
        figure that grows every time a stranger creates an account.
        """

    @abstractmethod
    async def record_event(self, event: ProjectEvent) -> None:
        """Append to the timeline without touching the project.

        Separate from `update`, which takes an optional event because most
        things worth recording are a change to the project. Some are not —
        photographs being shared changes assets, not the project — and calling
        `update` with an unmodified entity to smuggle an event in would make
        every write look like a change to anybody reading the code or the
        query log.
        """

    @abstractmethod
    async def list_events(self, project_id: UUID) -> list[ProjectEvent]: ...
