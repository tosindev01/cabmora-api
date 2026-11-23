from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import EntityNotFoundError
from app.domain.entities.issue_report import IssueReport, IssueStatus
from app.domain.repositories.issue_report_repository import IssueReportRepository
from app.infrastructure.models.issue_report import IssueReportModel


class SqlAlchemyIssueReportRepository(IssueReportRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, issue: IssueReport) -> IssueReport:
        model = IssueReportModel.from_entity(issue)
        self._session.add(model)
        await self._session.commit()
        return model.to_entity()

    async def get_by_id(self, issue_id: UUID) -> IssueReport | None:
        model = await self._session.get(IssueReportModel, str(issue_id))
        return model.to_entity() if model else None

    async def save(self, issue: IssueReport) -> IssueReport:
        model = await self._session.get(IssueReportModel, str(issue.id))
        if model is None:
            raise EntityNotFoundError("That report no longer exists.")
        # Field by field, and only the ones a status change touches. The
        # summary and detail are the reporter's words and are never rewritten
        # from a copy that has been sitting in an admin's browser.
        model.status = issue.status.value
        model.resolved_at = issue.resolved_at
        model.resolved_by = str(issue.resolved_by) if issue.resolved_by else None
        model.resolution = issue.resolution
        await self._session.commit()
        return model.to_entity()

    async def list_all(
        self, *, status: IssueStatus | None = None, limit: int = 100, offset: int = 0
    ) -> list[IssueReport]:
        query = select(IssueReportModel)
        if status is not None:
            query = query.where(IssueReportModel.status == status.value)
        query = query.order_by(IssueReportModel.created_at.desc()).limit(limit).offset(offset)
        rows = await self._session.execute(query)
        return [row.to_entity() for row in rows.scalars().all()]

    async def count_open(self) -> int:
        query = select(func.count()).select_from(IssueReportModel).where(
            IssueReportModel.status != IssueStatus.RESOLVED.value
        )
        return int((await self._session.execute(query)).scalar() or 0)

    async def list_for_reporter(self, reporter_id: UUID) -> list[IssueReport]:
        query = (
            select(IssueReportModel)
            .where(IssueReportModel.reporter_id == str(reporter_id))
            .order_by(IssueReportModel.created_at.desc())
        )
        rows = await self._session.execute(query)
        return [row.to_entity() for row in rows.scalars().all()]
