from datetime import datetime

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.entities.issue_report import IssueReport, IssueStatus
from app.infrastructure.database import Base


class IssueReportModel(Base):
    __tablename__ = "issue_reports"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    reporter_id: Mapped[str] = mapped_column(String(36), index=True)
    summary: Mapped[str] = mapped_column(String(160))
    detail: Mapped[str] = mapped_column(Text)
    page_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    #: Indexed because the console's default view is "the open ones", and that
    #: filter runs on every load of the inbox.
    status: Mapped[str] = mapped_column(String(20), index=True, default=IssueStatus.OPEN.value)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    resolution: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)

    def to_entity(self) -> IssueReport:
        from uuid import UUID

        return IssueReport(
            id=UUID(self.id),
            reporter_id=UUID(self.reporter_id),
            summary=self.summary,
            detail=self.detail,
            page_path=self.page_path,
            status=IssueStatus(self.status),
            resolved_at=self.resolved_at,
            resolved_by=UUID(self.resolved_by) if self.resolved_by else None,
            resolution=self.resolution,
            created_at=self.created_at,
        )

    @classmethod
    def from_entity(cls, issue: IssueReport) -> "IssueReportModel":
        return cls(
            id=str(issue.id),
            reporter_id=str(issue.reporter_id),
            summary=issue.summary,
            detail=issue.detail,
            page_path=issue.page_path,
            status=issue.status.value,
            resolved_at=issue.resolved_at,
            resolved_by=str(issue.resolved_by) if issue.resolved_by else None,
            resolution=issue.resolution,
            created_at=issue.created_at,
        )
