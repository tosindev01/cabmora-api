from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import (
    CurrentAdminDep,
    ReportsDep,
    get_grant_permissions,
    get_manage_access_groups,
    get_provision_account,
    CountDashboardDep,
    CreatorPerformanceDep,
    MonthlyReportDep,
    get_get_user,
    get_list_users,
    get_update_user,
)
from app.api.schemas.admin import (
    GroupMembersRequest,
    GroupRequest,
    GroupResponse,
    PermissionsRequest,
    UserGroupsRequest,
    AdminStatsResponse,
    EnquiryCountsResponse,
    CreatorPerformanceResponse,
    CreatorReportResponse,
    MonthlyPointResponse,
    MonthlyReportResponse,
    ProjectCountsResponse,
    AccountCreateRequest,
    ProvisionedAccountResponse,
    UserCountsResponse,
    UserUpdateRequest,
)
from app.api.schemas.page import Page
from app.application.use_cases.invites.provision_account import (
    ProvisionAccount,
)
from app.core.config import get_settings
from app.api.schemas.auth import UserResponse
from app.application.use_cases.admin.grant_permissions import GrantPermissions
from app.application.use_cases.admin.manage_access_groups import ManageAccessGroups
from app.application.use_cases.users.get_user import GetUser
from app.application.use_cases.users.list_users import DEFAULT_PAGE_SIZE, ListUsers
from app.application.use_cases.users.update_user import UpdateUser
from app.domain.entities.user import UserRole, UserStatus

router = APIRouter(prefix="/admin", tags=["admin"])


def _to_user_response(user) -> UserResponse:
    return UserResponse(
        id=user.id,
        email=user.email,
        first_name=user.first_name,
        last_name=user.last_name,
        full_name=user.full_name,
        phone=user.phone,
        whatsapp=user.whatsapp,
        role=user.role,
        status=user.status,
        granted=sorted(user.granted, key=lambda p: p.value),
        from_groups=sorted(user.from_groups, key=lambda p: p.value),
        group_names=user.group_names,
        reachable=sorted(user.reachable, key=lambda p: p.value),
        created_at=user.created_at,
    )


@router.get("/users", response_model=Page[UserResponse])
async def list_users(
    _admin: CurrentAdminDep,
    use_case: Annotated[ListUsers, Depends(get_list_users)],
    #: Repeatable: `?role=admin&role=coordinator` is the console's Team list.
    #: Keeps the singular name so a single `?role=creator` still works.
    role: list[UserRole] | None = Query(default=None),
    status: UserStatus | None = Query(default=None),
    q: str | None = Query(default=None, max_length=255, description="Name or email"),
    limit: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> Page[UserResponse]:
    """Admin-only — the PRD's "[M] User management".

    `?status=pending` is the acceptance queue. Filtering and search are done
    here rather than in the browser so that `total` describes the whole result
    set: a client-side filter over one page would report "3 pending" when it
    meant "3 pending on this page".
    """
    page = await use_case.execute(
        limit=limit, offset=offset, roles=role, status=status, search=q
    )
    return Page[UserResponse](
        items=[_to_user_response(u) for u in page.items],
        total=page.total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get("/users/{user_id}", response_model=UserResponse)
async def get_user(
    user_id: UUID,
    _admin: CurrentAdminDep,
    use_case: Annotated[GetUser, Depends(get_get_user)],
) -> UserResponse:
    """One account, for the detail view. 404 when the id is unknown."""
    return _to_user_response(await use_case.execute(user_id))


@router.patch("/users/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: UUID,
    body: UserUpdateRequest,
    admin: CurrentAdminDep,
    use_case: Annotated[UpdateUser, Depends(get_update_user)],
) -> UserResponse:
    """Change a role, or suspend and reinstate — the admin persona's "manage
    users' accessibility".

    The admin is bound rather than discarded because the use case needs to know
    who is acting in order to refuse a self-lockout.
    """
    user = await use_case.execute(
        user_id=user_id, actor_id=admin.id, role=body.role, status=body.status
    )
    return _to_user_response(user)


@router.put("/users/{user_id}/permissions", response_model=UserResponse)
async def set_user_permissions(
    user_id: UUID,
    body: PermissionsRequest,
    admin: CurrentAdminDep,
    use_case: Annotated[GrantPermissions, Depends(get_grant_permissions)],
) -> UserResponse:
    """Change which extra sections a coordinator may reach.

    Administrator-only, never on yourself, coordinators only, and only the
    sections on the grantable list — each refusal is an escalation if it is
    missed, so all four are enforced here rather than left to the console.
    """
    return _to_user_response(
        await use_case.execute(
            actor=admin, user_id=user_id, permissions=set(body.permissions)
        )
    )


@router.get("/stats", response_model=AdminStatsResponse)
async def stats(
    _admin: CurrentAdminDep,
    use_case: CountDashboardDep,
) -> AdminStatsResponse:
    """Headline numbers for the admin dashboard.

    Accounts, projects and enquiries, counted in the database rather than by
    listing and measuring — `list_all` is paginated and would report 30.

    Revenue is deliberately not here: it lives on `/admin/billing/stats`, which
    nets off refunds. Reviews are absent because no review entity exists, and
    returning zero would read as "none pending" rather than "not built".
    """
    counts = await use_case.execute()
    return AdminStatsResponse(
        users=UserCountsResponse(**counts.users.__dict__),
        projects=ProjectCountsResponse(**counts.projects.__dict__),
        enquiries=EnquiryCountsResponse(**counts.enquiries.__dict__),
    )


@router.get("/reports/creators", response_model=CreatorReportResponse)
async def creator_report(
    _: ReportsDep,
    use_case: CreatorPerformanceDep,
) -> CreatorReportResponse:
    """Workload and billing per creator, Cabmora included.

    The in-house row is always present, even at zero, so that Cabmora doing its
    own work is stated rather than inferred from an empty list.
    """
    rows = await use_case.execute()
    return CreatorReportResponse(
        currency="GBP",
        creators=[CreatorPerformanceResponse(**row.__dict__) for row in rows],
    )


@router.get("/reports/monthly", response_model=MonthlyReportResponse)
async def monthly_report(
    _: ReportsDep,
    use_case: MonthlyReportDep,
    months: int = 6,
) -> MonthlyReportResponse:
    """Registrations and revenue per calendar month, oldest first.

    Capped at two years server-side: a query string should not be able to ask
    for a decade of scanning.
    """
    points = await use_case.execute(months=months)
    return MonthlyReportResponse(
        currency="GBP",
        months=[MonthlyPointResponse(**p.__dict__) for p in points],
    )


@router.post(
    "/users",
    response_model=ProvisionedAccountResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_account(
    body: AccountCreateRequest,
    _admin: CurrentAdminDep,
    use_case: Annotated[ProvisionAccount, Depends(get_provision_account)],
) -> ProvisionedAccountResponse:
    """Create an account and email its holder an invite to set a password.

    Two uses. A customer whose project was booked from an enquiry: their
    details are already known, so they should not have to sign up to see
    their own work. And a new colleague — a coordinator or an administrator —
    who is added by name and email rather than told to register and then
    promoted.

    Where the invite link points follows from the role, inside the use case.
    """
    result = await use_case.execute(**body.model_dump())
    settings = get_settings()
    return ProvisionedAccountResponse(
        id=result.user.id,
        email=result.user.email,
        full_name=result.user.full_name,
        # Surfaced locally because the logging sender does not deliver; in
        # production their own inbox is the only place this link appears.
        invite_url=result.invite_url if settings.environment == "local" else None,
    )


# ── access groups ────────────────────────────────────────────
#: A named bundle of sections, assignable to coordinators. An additive role in
#: everything but name, bounded by the same grantable list as a direct grant —
#: a group containing "users" would be a ladder out of the whole mechanism.
GroupsDep = Annotated[ManageAccessGroups, Depends(get_manage_access_groups)]


def _group(group) -> GroupResponse:
    return GroupResponse(
        id=group.id,
        name=group.name,
        permissions=sorted(group.permissions, key=lambda p: p.value),
        member_count=group.member_count,
        created_at=group.created_at,
    )


@router.get("/groups", response_model=list[GroupResponse])
async def list_groups(admin: CurrentAdminDep, use_case: GroupsDep) -> list[GroupResponse]:
    return [_group(g) for g in await use_case.list_groups(actor=admin)]


@router.post("/groups", response_model=GroupResponse, status_code=status.HTTP_201_CREATED)
async def create_group(
    body: GroupRequest, admin: CurrentAdminDep, use_case: GroupsDep
) -> GroupResponse:
    return _group(
        await use_case.create(
            actor=admin, name=body.name, permissions=set(body.permissions)
        )
    )


@router.put("/groups/{group_id}", response_model=GroupResponse)
async def update_group(
    group_id: UUID, body: GroupRequest, admin: CurrentAdminDep, use_case: GroupsDep
) -> GroupResponse:
    """Rename it, or change what it gives.

    Changing the permissions changes them for everybody in the group at once.
    That is what a group is for, and it is why the response carries the member
    count — so the console can say what it just affected.
    """
    return _group(
        await use_case.update(
            actor=admin,
            group_id=group_id,
            name=body.name,
            permissions=set(body.permissions),
        )
    )


@router.delete("/groups/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_group(
    group_id: UUID, admin: CurrentAdminDep, use_case: GroupsDep
) -> None:
    """Remove the group and every membership of it."""
    await use_case.delete(actor=admin, group_id=group_id)


@router.get("/groups/{group_id}/members", response_model=list[UUID])
async def group_members(
    group_id: UUID, admin: CurrentAdminDep, use_case: GroupsDep
) -> list[UUID]:
    return await use_case.members(actor=admin, group_id=group_id)


@router.put("/groups/{group_id}/members", response_model=GroupResponse)
async def set_group_members(
    group_id: UUID,
    body: GroupMembersRequest,
    admin: CurrentAdminDep,
    use_case: GroupsDep,
) -> GroupResponse:
    return _group(
        await use_case.set_members(
            actor=admin, group_id=group_id, user_ids=set(body.user_ids)
        )
    )


@router.put("/users/{user_id}/groups", response_model=UserResponse)
async def set_user_groups(
    user_id: UUID,
    body: UserGroupsRequest,
    admin: CurrentAdminDep,
    use_case: GroupsDep,
) -> UserResponse:
    """The same change from the other end: which groups one person is in."""
    return _to_user_response(
        await use_case.set_groups_for_user(
            actor=admin, user_id=user_id, group_ids=set(body.group_ids)
        )
    )
