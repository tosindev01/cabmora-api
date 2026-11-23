from dataclasses import dataclass
from uuid import UUID

from app.domain.entities.invoice import InvoiceStatus
from app.domain.entities.project import ProjectStage
from app.domain.entities.user import UserRole
from app.domain.repositories.invoice_repository import InvoiceRepository
from app.domain.repositories.project_repository import ProjectRepository
from app.domain.repositories.user_repository import UserRepository

#: What an unassigned project is attributed to. `Project.creator_id` already
#: documents null as "Cabmora's own work"; this is the label that rule wears.
IN_HOUSE_NAME = "Cabmora"


@dataclass
class CreatorPerformance:
    #: None = Cabmora's own work rather than a partner's.
    creator_id: UUID | None
    name: str
    is_in_house: bool
    projects_total: int
    projects_active: int
    #: Net of confirmed refunds, on invoices raised against those projects.
    #: Deliberately "billed", not "earned" — a partner's share would need a
    #: commission model, and nothing computes one.
    revenue_minor: int


class CreatorPerformanceReport:
    """Per-creator workload and revenue, with Cabmora as the implicit creator.

    A project with no `creator_id` is Cabmora's own work, so it is attributed to
    an in-house row rather than dropped. Dropping it would make this panel
    disagree with the project count on the same dashboard — the kind of
    discrepancy that gets noticed and cannot be explained.

    The in-house row is always present, even at zero, so "Cabmora does its own
    work" is visible rather than inferred from an absence.

    Assembled in Python from three list reads. At current volumes that beats the
    three-way join it replaces; when it stops being cheap the answer is a rollup
    table, not a cleverer query — the same note as `MonthlyReport`.
    """

    def __init__(
        self,
        users: UserRepository,
        projects: ProjectRepository,
        invoices: InvoiceRepository,
    ) -> None:
        self._users = users
        self._projects = projects
        self._invoices = invoices

    async def execute(self) -> list[CreatorPerformance]:
        projects = await self._projects.list_all(limit=10_000, offset=0)

        # creator_id -> project ids. `None` is a real key here, not a missing
        # one: it is the in-house bucket.
        by_creator: dict[UUID | None, list[UUID]] = {None: []}
        active: dict[UUID | None, int] = {None: 0}
        for project in projects:
            by_creator.setdefault(project.creator_id, []).append(project.id)
            active.setdefault(project.creator_id, 0)
            if project.stage is not ProjectStage.CLOSED:
                active[project.creator_id] += 1

        # Every creator account appears, including one with no work yet —
        # a partner who has been onboarded and given nothing is exactly what an
        # administrator wants to see.
        for user in await self._users.list_all(limit=10_000, offset=0):
            if user.role is UserRole.CREATOR and user.id not in by_creator:
                by_creator[user.id] = []
                active[user.id] = 0

        project_to_creator = {
            project_id: creator_id
            for creator_id, ids in by_creator.items()
            for project_id in ids
        }

        revenue: dict[UUID | None, int] = {key: 0 for key in by_creator}
        for invoice in await self._invoices.list_all(limit=10_000, offset=0):
            # A voided invoice is not a claim on anyone; a draft was never sent.
            if invoice.status is not InvoiceStatus.ISSUED:
                continue
            creator_id = project_to_creator.get(invoice.project_id)
            if creator_id in revenue:
                revenue[creator_id] += invoice.paid_minor

        people = await self._users.get_many(
            {key for key in by_creator if key is not None}
        )

        rows = [
            CreatorPerformance(
                creator_id=creator_id,
                name=(
                    IN_HOUSE_NAME
                    if creator_id is None
                    else (
                        people[creator_id].full_name
                        if creator_id in people
                        else "Unknown creator"
                    )
                ),
                is_in_house=creator_id is None,
                projects_total=len(ids),
                projects_active=active.get(creator_id, 0),
                revenue_minor=revenue.get(creator_id, 0),
            )
            for creator_id, ids in by_creator.items()
        ]

        # Leading with who is billing most is what the panel is for.
        rows.sort(key=lambda row: (-row.revenue_minor, -row.projects_total, row.name))
        return rows
