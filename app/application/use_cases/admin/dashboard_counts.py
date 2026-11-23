from dataclasses import dataclass

from app.application.use_cases.users.count_users import CountUsers, UserCounts
from app.domain.entities.enquiry import EnquiryStatus
from app.domain.entities.project import ProjectStage
from app.domain.repositories.enquiry_repository import EnquiryRepository
from app.domain.repositories.project_repository import ProjectRepository
from app.domain.repositories.user_repository import UserRepository


@dataclass
class ProjectCounts:
    total: int
    #: Anything not CLOSED. "Active" is a question about the stage machine, so
    #: it is answered here once rather than by each client deciding for itself
    #: which stages count — the admin console and the portal would drift.
    active: int
    in_review: int
    delivered: int


@dataclass
class EnquiryCounts:
    total: int
    #: What the dashboard calls "pending" — nobody has picked it up yet.
    new: int
    consultation_booked: int


@dataclass
class DashboardCounts:
    users: UserCounts
    projects: ProjectCounts
    enquiries: EnquiryCounts


class CountDashboard:
    """Every headline figure on the admin overview, in one read.

    Counted in the database, never by listing and measuring in Python:
    `list_all` is paginated, so counting its result quietly reports 30 once
    there are more than 30 rows. That is the bug `CountUsers` already documents,
    and it is the one the fixture dashboard would have shipped.
    """

    def __init__(
        self,
        users: UserRepository,
        projects: ProjectRepository,
        enquiries: EnquiryRepository,
    ) -> None:
        self._count_users = CountUsers(users)
        self._projects = projects
        self._enquiries = enquiries

    async def execute(self) -> DashboardCounts:
        by_stage = {
            stage: await self._projects.count_all(stage=stage) for stage in ProjectStage
        }
        return DashboardCounts(
            users=await self._count_users.execute(),
            projects=ProjectCounts(
                total=sum(by_stage.values()),
                active=sum(
                    count
                    for stage, count in by_stage.items()
                    if stage is not ProjectStage.CLOSED
                ),
                in_review=by_stage.get(ProjectStage.IN_REVIEW, 0),
                delivered=by_stage.get(ProjectStage.DELIVERED, 0),
            ),
            enquiries=EnquiryCounts(
                total=await self._enquiries.count_all(),
                new=await self._enquiries.count_all(status=EnquiryStatus.NEW),
                consultation_booked=await self._enquiries.count_all(
                    status=EnquiryStatus.CONSULTATION_BOOKED
                ),
            ),
        )
