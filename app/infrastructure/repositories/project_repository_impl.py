from uuid import UUID

from datetime import date, datetime, timedelta, timezone

from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import EntityNotFoundError
from app.domain.entities.project import Project, ProjectStage
from app.domain.entities.project_event import ProjectEvent
from app.domain.repositories.project_repository import ProjectRepository
from app.infrastructure.models.user import UserModel
from app.infrastructure.models.project import (
    ProjectEventModel,
    ProjectMemberModel,
    ProjectModel,
)


#: Delivered or closed — the two stages that mean a shoot happened.
_COMPLETED = [ProjectStage.DELIVERED.value, ProjectStage.CLOSED.value]


class SqlAlchemyProjectRepository(ProjectRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @staticmethod
    def _filters(
        stage: ProjectStage | None,
        customer_id: UUID | None,
        creator_id: UUID | None,
        search: str | None,
        access_for: UUID | None = None,
        event_from: date | None = None,
        event_to: date | None = None,
        due_within_days: int | None = None,
    ) -> list:
        """Shared by list_all and count_all so the page and its total cannot
        describe different result sets.

        `access_for` is the scoping clause: the projects one member of staff
        may open. It belongs here, beside the other filters, rather than in a
        separate query — a second code path would have to re-implement stage,
        customer and search, and a coordinator whose filters silently stopped
        working would reach for the unscoped list instead.
        """
        clauses = []
        if access_for is not None:
            # This is the SQL of `Project.is_managed_by` for non-admin staff:
            # the assigned creator, or somebody on the team. Keep the two in
            # step. A list that shows a project the detail endpoint then
            # refuses is worse than one that never showed it.
            clauses.append(
                or_(
                    ProjectModel.creator_id == str(access_for),
                    ProjectModel.id.in_(
                        select(ProjectMemberModel.project_id).where(
                            ProjectMemberModel.user_id == str(access_for)
                        )
                    ),
                )
            )
        if stage is not None:
            clauses.append(ProjectModel.stage == stage.value)
        if customer_id is not None:
            clauses.append(ProjectModel.customer_id == str(customer_id))
        if creator_id is not None:
            clauses.append(ProjectModel.creator_id == str(creator_id))
        if search and search.strip():
            term = f"%{search.strip().lower()}%"
            # The customer's details live on another table, and an admin
            # looking for "that Hartley job" is as likely to have the client's
            # email or phone number in front of them as the project's title.
            #
            # EXISTS rather than a join: these clauses are shared by `list_all`
            # and `count_all`, and a join against a one-to-many would multiply
            # rows in the first and inflate the total in the second. EXISTS
            # cannot change the cardinality of the outer query.
            matches_customer = (
                select(UserModel.id)
                .where(UserModel.id == ProjectModel.customer_id)
                .where(
                    or_(
                        func.lower(UserModel.email).like(term),
                        func.lower(UserModel.phone).like(term),
                        func.lower(UserModel.whatsapp).like(term),
                        func.lower(
                            UserModel.first_name + " " + UserModel.last_name
                        ).like(term),
                    )
                )
                .exists()
            )
            clauses.append(
                or_(
                    func.lower(ProjectModel.title).like(term),
                    func.lower(ProjectModel.location).like(term),
                    func.lower(ProjectModel.event_type).like(term),
                    matches_customer,
                )
            )
        # Inclusive at both ends. An admin who types the 14th to the 16th
        # means those three days, not the day and a half in between.
        if event_from is not None:
            clauses.append(ProjectModel.event_date >= event_from)
        if event_to is not None:
            clauses.append(ProjectModel.event_date <= event_to)

        if due_within_days is not None:
            cutoff = date.today() + timedelta(days=due_within_days)
            clauses.append(
                and_(
                    # A project with no deadline is not due. NULL would be
                    # excluded by the comparison anyway, but saying it means
                    # nobody has to work that out from the SQL.
                    ProjectModel.deadline.is_not(None),
                    ProjectModel.deadline <= cutoff,
                    # Already-late work is the most urgent thing this can
                    # return, so overdue projects are included rather than
                    # filtered out by a lower bound.
                    #
                    # Delivered and closed are not: a finished job has no
                    # deadline pressure, and a "due soon" list padded with
                    # work that is done stops being read. Combine with an
                    # explicit `stage` to see those.
                    ProjectModel.stage.not_in(_COMPLETED),
                )
            )

        return clauses

    async def add(self, project: Project, event: ProjectEvent) -> Project:
        model = ProjectModel.from_entity(project)
        self._session.add(model)
        self._session.add(ProjectEventModel.from_entity(event))
        # One commit: a project without its CREATED event is a hole in the
        # audit trail, and two commits can leave exactly that.
        await self._session.commit()
        return model.to_entity()

    async def get_by_id(self, project_id: UUID) -> Project | None:
        model = await self._session.get(ProjectModel, str(project_id))
        if model is None:
            return None
        members = await self._members_for([str(project_id)])
        return model.to_entity(members.get(str(project_id), []))

    async def _members_for(self, project_ids: list[str]) -> dict[str, list[UUID]]:
        """Members for a page of projects, in one query.

        One query for thirty rows rather than thirty: a list endpoint that
        loads members per project is the classic N+1, and it only shows up
        once the studio has enough work to be worth listing.
        """
        if not project_ids:
            return {}
        rows = await self._session.execute(
            select(ProjectMemberModel).where(
                ProjectMemberModel.project_id.in_(project_ids)
            )
        )
        grouped: dict[str, list[UUID]] = {}
        for row in rows.scalars().all():
            grouped.setdefault(row.project_id, []).append(UUID(row.user_id))
        return grouped

    async def set_members(self, project_id: UUID, user_ids: list[UUID]) -> list[UUID]:
        """Replace the membership of a project.

        Replace rather than add/remove: the console edits this as a set, and
        two endpoints that can disagree about who is on a shoot is how
        somebody ends up still holding access they were taken off.
        """
        await self._session.execute(
            delete(ProjectMemberModel).where(
                ProjectMemberModel.project_id == str(project_id)
            )
        )
        now = datetime.now(timezone.utc)
        for user_id in dict.fromkeys(user_ids):
            self._session.add(
                ProjectMemberModel(
                    project_id=str(project_id), user_id=str(user_id), added_at=now
                )
            )
        await self._session.commit()
        return list(dict.fromkeys(user_ids))

    async def update(self, project: Project, event: ProjectEvent | None = None) -> Project:
        model = await self._session.get(ProjectModel, str(project.id))
        if model is None:
            raise EntityNotFoundError("Project not found")

        model.title = project.title
        model.description = project.description
        model.event_type = project.event_type
        model.location = project.location
        model.event_date = project.event_date
        model.deadline = project.deadline
        model.price_minor = project.price_minor
        model.payment_method = (
            project.payment_method.value if project.payment_method else None
        )
        model.creator_id = str(project.creator_id) if project.creator_id else None
        model.stage = project.stage.value
        model.watermark_policy = project.watermark_policy.value
        model.release_mode = project.release_mode.value
        model.require_approval_before_delivery = project.require_approval_before_delivery
        model.require_payment_before_delivery = project.require_payment_before_delivery
        model.allow_client_sharing = project.allow_client_sharing
        model.allow_downloads = project.allow_downloads
        model.approved_at = project.approved_at
        model.approved_by = str(project.approved_by) if project.approved_by else None
        # Assignment is allowed; *re*assignment is refused in UpdateProject.
        # Moving a project between customers would silently move their media
        # and their invoices with it.
        model.customer_id = str(project.customer_id) if project.customer_id else None

        if event is not None:
            self._session.add(ProjectEventModel.from_entity(event))
        await self._session.commit()
        return model.to_entity()

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
    ) -> list[Project]:
        stmt = (
            select(ProjectModel)
            .where(*self._filters(stage, customer_id, creator_id, search, access_for, event_from, event_to, due_within_days))
            .order_by(ProjectModel.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await self._session.execute(stmt)
        models = list(result.scalars().all())
        members = await self._members_for([m.id for m in models])
        return [m.to_entity(members.get(m.id, [])) for m in models]

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
    ) -> int:
        stmt = (
            select(func.count())
            .select_from(ProjectModel)
            .where(*self._filters(stage, customer_id, creator_id, search, access_for, event_from, event_to, due_within_days))
        )
        return (await self._session.execute(stmt)).scalar_one()

    async def event_types(self) -> list[str]:
        stmt = (
            select(ProjectModel.event_type)
            .where(ProjectModel.event_type != "")
            .distinct()
            .order_by(ProjectModel.event_type)
        )
        rows = await self._session.execute(stmt)
        return [value for (value,) in rows.all() if value]

    async def count_completed(self) -> int:
        stmt = (
            select(func.count())
            .select_from(ProjectModel)
            .where(ProjectModel.stage.in_(_COMPLETED))
        )
        return int((await self._session.execute(stmt)).scalar() or 0)

    async def count_clients_served(self) -> int:
        stmt = (
            select(func.count(func.distinct(ProjectModel.customer_id)))
            .where(ProjectModel.stage.in_(_COMPLETED))
            # A project set up before its client had an account carries no
            # customer_id, and counting NULL as a client would inflate this.
            .where(ProjectModel.customer_id.is_not(None))
        )
        return int((await self._session.execute(stmt)).scalar() or 0)

    async def record_event(self, event: ProjectEvent) -> None:
        self._session.add(ProjectEventModel.from_entity(event))
        await self._session.commit()

    async def list_events(self, project_id: UUID) -> list[ProjectEvent]:
        stmt = (
            select(ProjectEventModel)
            .where(ProjectEventModel.project_id == str(project_id))
            # Oldest first: this renders as a timeline, which reads forwards.
            .order_by(ProjectEventModel.occurred_at.asc())
        )
        result = await self._session.execute(stmt)
        # Events carry no membership — they are what happened, not who is on it.
        return [m.to_entity() for m in result.scalars().all()]
