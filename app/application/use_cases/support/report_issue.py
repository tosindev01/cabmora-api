"""Anyone signed in can say something is broken.

No role check. A customer hitting a bug is the person best placed to report it,
and a support channel that only staff may use reports only the bugs staff
happen to hit.
"""

from dataclasses import dataclass
from uuid import UUID

from app.domain.entities.issue_report import IssueReport
from app.domain.entities.user import User
from app.application.use_cases.notifications.notifier import Notifier
from app.domain.repositories.issue_report_repository import IssueReportRepository
from app.domain.repositories.user_repository import UserRepository


@dataclass(frozen=True)
class ReportedIssue:
    issue: IssueReport
    reporter_name: str
    reporter_email: str


class ReportIssue:
    def __init__(self, issues: IssueReportRepository, notifier: Notifier) -> None:
        self._issues = issues
        self._notifier = notifier

    async def execute(
        self, *, actor: User, summary: str, detail: str, page_path: str | None
    ) -> IssueReport:
        # Validation lives in the entity, so the same rules apply wherever one
        # is built — including a seed script or a future email-in channel.
        issue = await self._issues.add(
            IssueReport(
                reporter_id=actor.id,
                summary=summary,
                detail=detail,
                page_path=page_path,
            )
        )
        # The reporter is left out: they pressed the button, and a bell telling
        # them what they just did is the fastest way to teach somebody to
        # ignore the bell.
        await self._notifier.issue_reported(
            summary=issue.summary,
            reporter_name=actor.full_name,
            reporter_id=actor.id,
        )
        return issue


class ListMyIssues:
    """What this person has reported, so they can see it arrived."""

    def __init__(self, issues: IssueReportRepository) -> None:
        self._issues = issues

    async def execute(self, *, actor: User) -> list[IssueReport]:
        return await self._issues.list_for_reporter(actor.id)


class ListIssues:
    """The console inbox, with reporters resolved for display."""

    def __init__(self, issues: IssueReportRepository, users: UserRepository) -> None:
        self._issues = issues
        self._users = users

    async def execute(self, *, status=None, limit: int = 100, offset: int = 0):
        issues = await self._issues.list_all(status=status, limit=limit, offset=offset)
        # One lookup for the page rather than one per row — the N+1 that makes
        # an inbox of fifty feel broken.
        people = await self._users.get_many({issue.reporter_id for issue in issues})
        return [
            ReportedIssue(
                issue=issue,
                reporter_name=_name(people.get(issue.reporter_id)),
                reporter_email=getattr(people.get(issue.reporter_id), "email", ""),
            )
            for issue in issues
        ]


def _name(user: User | None) -> str:
    # A deleted or missing account must not blank the row: the report is still
    # real and still needs reading.
    return user.full_name if user else "A former account"


class UpdateIssue:
    """Move a report along. Console-side; the guard is on the router."""

    def __init__(self, issues: IssueReportRepository) -> None:
        self._issues = issues

    async def execute(self, *, issue_id: UUID, actor: User, status, resolution: str | None):
        issue = await self._issues.get_by_id(issue_id)
        if issue is None:
            from app.core.exceptions import EntityNotFoundError

            raise EntityNotFoundError("That report no longer exists.")

        issue.move_to(status, by=actor.id, resolution=resolution)
        return await self._issues.save(issue)
