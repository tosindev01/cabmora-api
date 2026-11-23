"""Applying to Cabmora Flow, and reviewing who applied.

Two audiences on one resource. `POST /creators/apply` is public — the whole
point is that a photographer who has never heard of us can ask. Everything
else is the review queue and is admin-only, because approving is the only act
in the system that creates a `creator`.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import (
    CreatorApplicationsDep,
    get_get_creator_application,
    get_list_creator_applications,
    get_review_creator_application,
    get_submit_creator_application,
)
from app.api.schemas.creator import (
    AdminCreatorApplicationResponse,
    ApprovalResponse,
    CreatorApplicationRequest,
    CreatorApplicationResponse,
    DeclineRequest,
)
from app.api.schemas.page import Page
from app.application.use_cases.creators.list_applications import (
    GetCreatorApplication,
    ListCreatorApplications,
)
from app.application.use_cases.creators.review_application import (
    ReviewCreatorApplication,
)
from app.application.use_cases.creators.submit_application import (
    SubmitCreatorApplication,
)
from app.core.config import get_settings
from app.domain.entities.creator_application import (
    ApplicationStatus,
    CreatorApplication,
)

router = APIRouter(prefix="/creators", tags=["creators"])
admin_router = APIRouter(prefix="/admin/creator-applications", tags=["admin: creators"])


def _admin_view(a: CreatorApplication) -> AdminCreatorApplicationResponse:
    return AdminCreatorApplicationResponse(
        id=a.id,
        studio_name=a.studio_name,
        status=a.status.value,
        created_at=a.created_at,
        applicant_name=a.applicant_name,
        email=a.email,
        portfolio_url=a.portfolio_url,
        discipline=a.discipline,
        annual_volume=a.annual_volume,
        storage_needs=a.storage_needs,
        bottleneck=a.bottleneck,
        plan=a.plan,
        decision_note=a.decision_note,
        reviewed_by=a.reviewed_by,
        reviewed_at=a.reviewed_at,
        created_user_id=a.created_user_id,
    )


@router.post(
    "/apply",
    response_model=CreatorApplicationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def apply(
    body: CreatorApplicationRequest,
    use_case: Annotated[SubmitCreatorApplication, Depends(get_submit_creator_application)],
) -> CreatorApplicationResponse:
    """Apply to deliver work through Flow.

    Answers 201 for a fresh application and for a repeat from an address that
    already has one pending — the second is not an error to the person making
    it, and saying so would tell a stranger which studios have applied.
    """
    application = await use_case.execute(
        studio_name=body.studio_name,
        applicant_name=body.applicant_name,
        email=body.email,
        portfolio_url=body.portfolio_url,
        discipline=body.discipline,
        annual_volume=body.annual_volume,
        storage_needs=body.storage_needs,
        bottleneck=body.bottleneck,
        plan=body.plan,
    )
    return CreatorApplicationResponse(
        id=application.id,
        studio_name=application.studio_name,
        status=application.status.value,
        created_at=application.created_at,
    )


@admin_router.get("", response_model=Page[AdminCreatorApplicationResponse])
async def list_applications(
    admin: CreatorApplicationsDep,
    use_case: Annotated[ListCreatorApplications, Depends(get_list_creator_applications)],
    application_status: ApplicationStatus | None = Query(default=None, alias="status"),
    limit: int = Query(default=30, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> Page[AdminCreatorApplicationResponse]:
    page = await use_case.execute(
        status=application_status, limit=limit, offset=offset
    )
    return Page(
        items=[_admin_view(a) for a in page.items],
        total=page.total,
        limit=limit,
        offset=offset,
    )


@admin_router.get("/{application_id}", response_model=AdminCreatorApplicationResponse)
async def get_application(
    application_id: UUID,
    admin: CreatorApplicationsDep,
    use_case: Annotated[GetCreatorApplication, Depends(get_get_creator_application)],
) -> AdminCreatorApplicationResponse:
    return _admin_view(await use_case.execute(application_id))


@admin_router.post("/{application_id}/approve", response_model=ApprovalResponse)
async def approve_application(
    application_id: UUID,
    admin: CreatorApplicationsDep,
    use_case: Annotated[ReviewCreatorApplication, Depends(get_review_creator_application)],
) -> ApprovalResponse:
    """Approve a studio: create their creator account and invite them in."""
    result = await use_case.approve(application_id=application_id, actor=admin)
    return ApprovalResponse(
        application=_admin_view(result.application),
        # A link that sets a password does not belong in a deployed response.
        setup_url=(
            result.setup_url if get_settings().environment == "local" else None
        ),
    )


@admin_router.post(
    "/{application_id}/decline", response_model=AdminCreatorApplicationResponse
)
async def decline_application(
    application_id: UUID,
    body: DeclineRequest,
    admin: CreatorApplicationsDep,
    use_case: Annotated[ReviewCreatorApplication, Depends(get_review_creator_application)],
) -> AdminCreatorApplicationResponse:
    return _admin_view(
        await use_case.decline(
            application_id=application_id, actor=admin, note=body.note
        )
    )
