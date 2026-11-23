from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.domain.entities.issue_report import MAX_DETAIL, MAX_SUMMARY, IssueStatus


class IssueCreateRequest(BaseModel):
    summary: str = Field(min_length=1, max_length=MAX_SUMMARY)
    detail: str = Field(min_length=1, max_length=MAX_DETAIL)
    #: Captured by the page, not typed. Clipped rather than rejected: a long
    #: URL is no reason to lose the report attached to it.
    page_path: str | None = Field(default=None, max_length=512)


class IssueResponse(BaseModel):
    id: UUID
    summary: str
    detail: str
    page_path: str | None
    status: IssueStatus
    created_at: datetime
    resolved_at: datetime | None = None
    resolution: str | None = None


class AdminIssueResponse(IssueResponse):
    """The same report, plus who sent it. Console only — a reporter has no
    business learning the names of other reporters."""

    reporter_name: str
    reporter_email: str


class IssueUpdateRequest(BaseModel):
    status: IssueStatus
    #: Only meaningful when resolving. Kept optional so "mark as resolved"
    #: stays one click when there is nothing to add.
    resolution: str | None = Field(default=None, max_length=MAX_DETAIL)
