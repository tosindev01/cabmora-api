"""Reporting something that is broken, and the console inbox that receives it.

Two routers in one file because they are two halves of one feature: anybody
signed in may report, and only an administrator may read the pile. Splitting
them across files would hide that the second exists.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import (
    CurrentActiveUserDep,
    CurrentAdminDep,
    get_list_issues,
    get_list_my_issues,
    get_report_issue,
    get_update_issue,
)
from app.api.schemas.support import (
    AdminIssueResponse,
    IssueCreateRequest,
    IssueResponse,
    IssueUpdateRequest,
)
from app.application.use_cases.support.report_issue import (
    ListIssues,
    ListMyIssues,
    ReportIssue,
    UpdateIssue,
)
from app.domain.entities.issue_report import IssueReport, IssueStatus

router = APIRouter(prefix="/issues", tags=["support"])
admin_router = APIRouter(prefix="/admin/issues", tags=["support"])


def _response(issue: IssueReport) -> IssueResponse:
    return IssueResponse(
        id=issue.id,
        summary=issue.summary,
        detail=issue.detail,
        page_path=issue.page_path,
        status=issue.status,
        created_at=issue.created_at,
        resolved_at=issue.resolved_at,
        resolution=issue.resolution,
    )


@router.post("", response_model=IssueResponse, status_code=status.HTTP_201_CREATED)
async def report_issue(
    body: IssueCreateRequest,
    actor: CurrentActiveUserDep,
    use_case: Annotated[ReportIssue, Depends(get_report_issue)],
) -> IssueResponse:
    """Say something is wrong. Open to every signed-in account, by design."""
    return _response(
        await use_case.execute(
            actor=actor,
            summary=body.summary,
            detail=body.detail,
            page_path=body.page_path,
        )
    )


@router.get("", response_model=list[IssueResponse])
async def my_issues(
    actor: CurrentActiveUserDep,
    use_case: Annotated[ListMyIssues, Depends(get_list_my_issues)],
) -> list[IssueResponse]:
    """What the caller has reported. Scoped by the use case, not by a
    parameter — a reporter id in a query string is how one person reads
    another's reports."""
    return [_response(issue) for issue in await use_case.execute(actor=actor)]


@admin_router.get("", response_model=list[AdminIssueResponse])
async def list_issues(
    _: CurrentAdminDep,
    use_case: Annotated[ListIssues, Depends(get_list_issues)],
    issue_status: IssueStatus | None = Query(default=None, alias="status"),
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[AdminIssueResponse]:
    """The inbox.

    Administrators only for now. It is not one of the grantable sections, so a
    coordinator cannot be let in without widening the permission union — worth
    doing once there is enough traffic for somebody other than an admin to be
    triaging it.
    """
    return [
        AdminIssueResponse(
            **_response(reported.issue).model_dump(),
            reporter_name=reported.reporter_name,
            reporter_email=reported.reporter_email,
        )
        for reported in await use_case.execute(
            status=issue_status, limit=limit, offset=offset
        )
    ]


@admin_router.patch("/{issue_id}", response_model=IssueResponse)
async def update_issue(
    issue_id: UUID,
    body: IssueUpdateRequest,
    actor: CurrentAdminDep,
    use_case: Annotated[UpdateIssue, Depends(get_update_issue)],
) -> IssueResponse:
    return _response(
        await use_case.execute(
            issue_id=issue_id,
            actor=actor,
            status=body.status,
            resolution=body.resolution,
        )
    )
