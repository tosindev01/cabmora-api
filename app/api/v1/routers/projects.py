"""Project endpoints.

Two audiences, two routers, one set of use cases:

* `/admin/projects` — creating, editing, moving stages, and the settings pages.
  Guarded by `CurrentAdminDep`.
* `/projects` — what a customer sees of their own work. Guarded by
  `CurrentActiveUserDep` plus a row-level check inside the use case, because a
  role says what kind of user you are and not which rows are yours.
"""

from typing import Annotated
from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from app.core.config import get_settings

from app.api.deps import (
    CurrentActiveUserDep,
    CurrentAdminDep,
    CurrentTeamDep,
    get_approve_project,
    get_change_project_stage,
    get_create_project,
    get_get_project,
    get_list_projects,
    get_rate_project,
    get_set_project_members,
    get_summarise_projects,
    get_update_project,
    PaginationDep,
    ProjectRepoDep,
    UserRepoDep,
)
from app.api.schemas.page import Page
from app.api.schemas.project import (
    ProjectMembersRequest,
    RatingRequest,
    RatingResponse,
    ProjectCreateRequest,
    ProjectDetailResponse,
    ProjectEventResponse,
    ProjectResponse,
    ProjectStageRequest,
    ProjectSummaryResponse,
    ProjectUpdateRequest,
)
from app.application.use_cases.projects.change_project_stage import ChangeProjectStage
from app.application.use_cases.projects.create_project import CreateProject
from app.application.use_cases.projects.approve_project import ApproveProject
from app.application.use_cases.projects.get_project import GetProject
from app.application.use_cases.projects.rate_project import RateProject
from app.application.use_cases.projects.set_project_members import SetProjectMembers
from app.application.use_cases.projects.list_projects import ListProjects
from app.application.use_cases.projects.summarise_projects import (
    ProjectSummary,
    SummariseProjects,
)
from app.application.use_cases.projects.update_project import UpdateProject
from app.domain.entities.project import Project, ProjectStage
from app.domain.entities.user import User

admin_router = APIRouter(prefix="/admin/projects", tags=["admin: projects"])
router = APIRouter(prefix="/projects", tags=["projects"])


#: Fields the entity does not carry — computed or looked up at response time.
_DERIVED = {"progress", "allowed_next_stages", "customer_name", "creator_name", "summary"}


def _to_response(
    project: Project,
    names: dict[UUID, User],
    summary: ProjectSummary | None = None,
) -> ProjectResponse:
    customer = names.get(project.customer_id) if project.customer_id else None
    creator = names.get(project.creator_id) if project.creator_id else None
    return ProjectResponse(
        **{
            field: getattr(project, field)
            for field in ProjectResponse.model_fields
            if field not in _DERIVED
        },
        progress=project.progress,
        allowed_next_stages=project.allowed_next_stages,
        # A deleted or missing user should not 500 a list of projects.
        # None when unassigned; "Unknown" only when the row vanished, which
        # should not 500 a list of projects.
        customer_name=(customer.full_name if customer else None)
        if project.customer_id is None or customer
        else "Unknown",
        creator_name=creator.full_name if creator else None,
        summary=ProjectSummaryResponse(
            photos=summary.photos,
            released=summary.released,
            open_comments=summary.open_comments,
            billed_minor=summary.billed_minor,
            paid_minor=summary.paid_minor,
            outstanding_minor=summary.outstanding_minor,
        )
        if summary
        else None,
    )


def _detail(
    project: Project,
    names: dict[UUID, User],
    events: list,
    summary: ProjectSummary | None = None,
) -> ProjectDetailResponse:
    """The project, its timeline, and how to reach the client.

    The contact details are read from the customer's account rather than
    stored on the project, so a client who changes their number changes it
    once.
    """
    customer = names.get(project.customer_id) if project.customer_id else None
    return ProjectDetailResponse(
        **_to_response(project, names, summary).model_dump(),
        events=[ProjectEventResponse.model_validate(e, from_attributes=True) for e in events],
        customer_email=customer.email if customer else None,
        customer_phone=customer.phone if customer else None,
        customer_whatsapp=customer.whatsapp if customer else None,
    )


async def _names_for(users: UserRepoDep, *projects: Project) -> dict[UUID, User]:
    """One lookup covering every customer and creator on the page."""
    ids = {p.customer_id for p in projects if p.customer_id} | {
        p.creator_id for p in projects if p.creator_id
    }
    return await users.get_many(ids)


# --- Admin ----------------------------------------------------------------


@admin_router.post("", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
async def create_project(
    body: ProjectCreateRequest,
    admin: CurrentAdminDep,  # creating work is a business act, not a shoot task
    use_case: Annotated[CreateProject, Depends(get_create_project)],
    users: UserRepoDep = None,  # type: ignore[assignment]
) -> ProjectResponse:
    project = await use_case.execute(actor_id=admin.id, **body.model_dump())
    return _to_response(project, await _names_for(users, project))


@admin_router.get("", response_model=Page[ProjectResponse])
async def list_projects(
    actor: CurrentTeamDep,
    page: PaginationDep,
    use_case: Annotated[ListProjects, Depends(get_list_projects)],
    summarise: Annotated[SummariseProjects, Depends(get_summarise_projects)],
    stage: ProjectStage | None = Query(default=None),
    customer_id: UUID | None = Query(default=None),
    creator_id: UUID | None = Query(default=None),
    #: "What can this person open?" — the inverse of a project's team list.
    #: Ignored for a coordinator, who is always scoped to their own.
    access_for: UUID | None = Query(default=None),
    q: str | None = Query(default=None, max_length=255),
    #: Inclusive both ends — the 14th to the 16th means those three days.
    event_from: date | None = Query(default=None),
    event_to: date | None = Query(default=None),
    #: Deadline on or before today plus this many days. Includes work that is
    #: already late, and excludes delivered and closed projects — a "due soon"
    #: list padded with finished jobs stops being read.
    due_within_days: int | None = Query(default=None, ge=0, le=365),
    users: UserRepoDep = None,  # type: ignore[assignment]
) -> Page[ProjectResponse]:
    result = await use_case.execute(
        actor,
        limit=page.limit, offset=page.offset, stage=stage,
        customer_id=customer_id, creator_id=creator_id, search=q,
        event_from=event_from, event_to=event_to,
        due_within_days=due_within_days,
        access_for=access_for,
    )
    names = await _names_for(users, *result.items)
    # Three queries for the page, not three per card.
    summaries = await summarise.execute([p.id for p in result.items])
    return Page[ProjectResponse](
        items=[_to_response(p, names, summaries.get(p.id)) for p in result.items],
        total=result.total,
        limit=result.limit,
        offset=result.offset,
    )


@admin_router.get("/event-types", response_model=list[str])
async def event_types(
    _team: CurrentTeamDep,
    projects: ProjectRepoDep,
) -> list[str]:
    """Categories already in use, for the picker on a project.

    **Declared above `/{project_id}`.** FastAPI matches in definition order,
    so below it the literal path is read as a project id and the request 422s
    on a malformed UUID — the same trap `/triage` has on enquiries.
    """
    return await projects.event_types()


@admin_router.put("/{project_id}/members", response_model=ProjectResponse)
async def set_members(
    project_id: UUID,
    body: ProjectMembersRequest,
    # Admin, deliberately: a coordinator who could add themselves to a
    # project could reach every client in the system.
    admin: CurrentAdminDep,
    use_case: Annotated[SetProjectMembers, Depends(get_set_project_members)],
    users: UserRepoDep = None,  # type: ignore[assignment]
) -> ProjectResponse:
    """Put Cabmora people on a shoot."""
    project = await use_case.execute(project_id=project_id, user_ids=body.user_ids)
    return _to_response(project, await _names_for(users, project))


@admin_router.get("/{project_id}", response_model=ProjectDetailResponse)
async def get_project_admin(
    project_id: UUID,
    actor: CurrentTeamDep,
    use_case: Annotated[GetProject, Depends(get_get_project)],
    summarise: Annotated[SummariseProjects, Depends(get_summarise_projects)],
    users: UserRepoDep = None,  # type: ignore[assignment]
) -> ProjectDetailResponse:
    """Summarised like the list, because the settings page now has to read the
    money: since the watermark lifts on payment rather than on approval, the
    screen cannot say what a client will see without knowing whether the job
    has been paid for."""
    project, events = await use_case.execute(project_id, actor)
    names = await _names_for(users, project)
    summaries = await summarise.execute([project.id])
    return _detail(project, names, events, summaries.get(project.id))


@admin_router.patch("/{project_id}", response_model=ProjectResponse)
async def update_project(
    project_id: UUID,
    body: ProjectUpdateRequest,
    actor: CurrentTeamDep,
    use_case: Annotated[UpdateProject, Depends(get_update_project)],
    users: UserRepoDep = None,  # type: ignore[assignment]
) -> ProjectResponse:
    """Details and the four delivery settings — the project settings page."""
    changes = body.model_dump(exclude_unset=True)
    project = await use_case.execute(project_id, actor, changes)
    return _to_response(project, await _names_for(users, project))


@admin_router.post("/{project_id}/stage", response_model=ProjectResponse)
async def change_stage(
    project_id: UUID,
    body: ProjectStageRequest,
    actor: CurrentTeamDep,
    use_case: Annotated[ChangeProjectStage, Depends(get_change_project_stage)],
    users: UserRepoDep = None,  # type: ignore[assignment]
) -> ProjectResponse:
    """Separate from PATCH so the transition rules always run."""
    project = await use_case.execute(project_id, actor, body.stage)
    return _to_response(project, await _names_for(users, project))


# --- Customer -------------------------------------------------------------


@router.get("", response_model=Page[ProjectResponse])
async def list_my_projects(
    user: CurrentActiveUserDep,
    page: PaginationDep,
    use_case: Annotated[ListProjects, Depends(get_list_projects)],
    summarise: Annotated[SummariseProjects, Depends(get_summarise_projects)],
    users: UserRepoDep = None,  # type: ignore[assignment]
) -> Page[ProjectResponse]:
    """Only the caller's own projects.

    `customer_id` is taken from the session, never from a query parameter —
    accepting it from the client would make every customer's work readable by
    changing a number in the URL.

    Summarised like the admin list, because the counts answer the client's
    questions too: are there photographs I can look at, is anything waiting
    on me, do I owe anything. Every figure in the summary is already theirs —
    their gallery, their change requests, their invoice — so it tells them
    nothing they could not get by opening the project.
    """
    result = await use_case.execute(
        user, limit=page.limit, offset=page.offset, customer_id=user.id
    )
    # No stage filter. A draft used to be stripped out here, which meant
    # `total` counted rows that were never returned — the client was told they
    # had a project and shown nothing — and a page could come back shorter
    # than the page size. Ownership is the whole rule now, and the query above
    # applies it, so `items` and `total` describe the same set.
    names = await _names_for(users, *result.items)
    summaries = await summarise.execute([p.id for p in result.items])
    return Page[ProjectResponse](
        items=[_to_response(p, names, summaries.get(p.id)) for p in result.items],
        total=result.total,
        limit=result.limit,
        offset=result.offset,
    )


@router.get("/{project_id}", response_model=ProjectDetailResponse)
async def get_my_project(
    project_id: UUID,
    user: CurrentActiveUserDep,
    use_case: Annotated[GetProject, Depends(get_get_project)],
    users: UserRepoDep = None,  # type: ignore[assignment]
) -> ProjectDetailResponse:
    project, events = await use_case.execute(project_id, user)
    return ProjectDetailResponse(
        **_to_response(project, await _names_for(users, project)).model_dump(),
        events=[ProjectEventResponse.model_validate(e, from_attributes=True) for e in events],
    )


def _rating(rating) -> RatingResponse:
    place = get_settings().google_place_id
    return RatingResponse(
        stars=rating.stars,
        words=rating.words,
        may_publish=rating.may_publish,
        created_at=rating.created_at,
        updated_at=rating.updated_at,
        # Google's own review form, with our listing already chosen. There is
        # no API that posts a review for somebody, and pretending otherwise
        # would mean either inventing reviews or silently dropping them.
        google_review_url=(
            f"https://search.google.com/local/writereview?placeid={place}"
            if place
            else None
        ),
    )


@router.put("/{project_id}/rating", response_model=RatingResponse)
async def rate_my_project(
    project_id: UUID,
    body: RatingRequest,
    user: CurrentActiveUserDep,
    use_case: Annotated[RateProject, Depends(get_rate_project)],
) -> RatingResponse:
    """Score the finished work.

    PUT rather than POST: there is one rating per project and sending it twice
    means the client changed their mind, not that they left two.
    """
    rating = await use_case.execute(
        project_id=project_id,
        actor=user,
        stars=body.stars,
        words=body.words,
        may_publish=body.may_publish,
    )
    return _rating(rating)


@router.get("/{project_id}/rating", response_model=RatingResponse | None)
async def get_my_project_rating(
    project_id: UUID,
    user: CurrentActiveUserDep,
    use_case: Annotated[RateProject, Depends(get_rate_project)],
) -> RatingResponse | None:
    """What they said last time, so the stars open where they left them."""
    rating = await use_case.current(project_id=project_id, actor=user)
    return _rating(rating) if rating else None


@router.post("/{project_id}/approve", response_model=ProjectResponse)
async def approve_project(
    project_id: UUID,
    user: CurrentActiveUserDep,
    use_case: Annotated[ApproveProject, Depends(get_approve_project)],
    users: UserRepoDep = None,  # type: ignore[assignment]
) -> ProjectResponse:
    """The client accepts the work.

    Deliberately not a PATCH of `stage`: approval is one move with one actor
    and a record attached, and routing it through the general stage endpoint
    would need that endpoint to stop being manager-only.
    """
    project = await use_case.execute(project_id, user)
    return _to_response(project, await _names_for(users, project))
