from abc import ABC, abstractmethod
from uuid import UUID

from app.domain.entities.issue_report import IssueReport, IssueStatus


class IssueReportRepository(ABC):
    @abstractmethod
    async def add(self, issue: IssueReport) -> IssueReport: ...

    @abstractmethod
    async def get_by_id(self, issue_id: UUID) -> IssueReport | None: ...

    @abstractmethod
    async def save(self, issue: IssueReport) -> IssueReport:
        """Write back a status change and its closing note."""

    @abstractmethod
    async def list_all(
        self, *, status: IssueStatus | None = None, limit: int = 100, offset: int = 0
    ) -> list[IssueReport]:
        """Newest first. `status=None` means every state, including resolved."""

    @abstractmethod
    async def count_open(self) -> int:
        """For the badge on the console. Resolved rows are not counted."""

    @abstractmethod
    async def list_for_reporter(self, reporter_id: UUID) -> list[IssueReport]:
        """What one person has reported, so they can see it was received."""
