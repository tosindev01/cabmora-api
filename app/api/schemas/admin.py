from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, model_validator

from app.domain.entities.user import Permission, UserRole, UserStatus


class UserUpdateRequest(BaseModel):
    """Both fields optional — this is a PATCH, so absent means "leave alone".

    Accepting a creator is `status: "active"`; suspending anyone is
    `status: "suspended"`. Unlike registration this *does* take a real
    `UserRole`, which is safe because the route is behind `CurrentAdminDep`.
    """

    role: UserRole | None = None
    status: UserStatus | None = None

    @model_validator(mode="after")
    def _reject_an_empty_patch(self) -> "UserUpdateRequest":
        # An empty body would otherwise be a 200 that changed nothing, which
        # reads as success to a caller that forgot to send its payload.
        if self.role is None and self.status is None:
            raise ValueError("Provide at least one of `role` or `status`.")
        return self


class PermissionsRequest(BaseModel):
    """The whole set, not a delta — for the same reason a project's members
    are sent whole: add and remove endpoints that can disagree are how
    somebody keeps access they were taken off."""

    permissions: list[Permission] = Field(default_factory=list, max_length=20)


class GroupRequest(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    permissions: list[Permission] = Field(default_factory=list, max_length=20)


class GroupMembersRequest(BaseModel):
    """Who is in the group, as the whole set."""

    user_ids: list[UUID] = Field(default_factory=list, max_length=200)


class UserGroupsRequest(BaseModel):
    """Which groups one person is in, as the whole set."""

    group_ids: list[UUID] = Field(default_factory=list, max_length=50)


class GroupResponse(BaseModel):
    id: UUID
    name: str
    permissions: list[Permission]
    #: How many people are in it. Published so the console can say what an
    #: edit is about to affect before it happens — the only warning between
    #: changing a group and nine people silently gaining a section.
    member_count: int
    created_at: datetime


class UserCountsResponse(BaseModel):
    total: int
    pending: int
    active: int
    suspended: int
    customers: int
    creators: int
    admins: int


class ProjectCountsResponse(BaseModel):
    total: int
    #: Anything not closed. Derived server-side so the console and the portal
    #: cannot disagree about what "active" means.
    active: int
    in_review: int
    delivered: int


class EnquiryCountsResponse(BaseModel):
    total: int
    #: Unclaimed. What the dashboard calls "pending".
    new: int
    consultation_booked: int


class AdminStatsResponse(BaseModel):
    """Only what is actually true.

    Projects and enquiries are here now that both exist. Revenue is not: it
    comes from `/admin/billing/stats`, which knows about refunds. Reviews are
    still absent because there is no review entity — an admin console is
    exactly where a fabricated number turns into a bad decision.
    """

    users: UserCountsResponse
    projects: ProjectCountsResponse
    enquiries: EnquiryCountsResponse


class MonthlyPointResponse(BaseModel):
    #: "2026-06". A month with no activity is still present with zeroes, or a
    #: chart closes the gap and a quiet month reads as a missing one.
    month: str
    customers: int
    creators: int
    revenue_minor: int


class CreatorPerformanceResponse(BaseModel):
    """One row per creator, plus Cabmora for work with no partner assigned."""

    #: Null on the in-house row — `Project.creator_id` null means Cabmora's own
    #: work, and this is that rule counted rather than merely documented.
    creator_id: UUID | None
    name: str
    is_in_house: bool
    projects_total: int
    projects_active: int
    #: Billed, not earned: a partner's share needs a commission model and there
    #: is not one.
    revenue_minor: int


class CreatorReportResponse(BaseModel):
    currency: str
    creators: list[CreatorPerformanceResponse]


class MonthlyReportResponse(BaseModel):
    currency: str
    months: list[MonthlyPointResponse]


class AccountCreateRequest(BaseModel):
    """Provision an account for somebody who has not signed up.

    No password field: they set their own from the invite link, so the admin
    never knows it — which is the whole reason this is not "an admin types a
    temporary password and reads it down the phone".

    `role` defaults to customer, which is how this endpoint began and what the
    new-project flow still sends. An admin may create staff here too; they can
    already create an account and then change its role, so refusing would
    only add a step, not a safeguard.
    """

    email: EmailStr
    first_name: str = Field(min_length=1, max_length=120)
    last_name: str = Field(min_length=1, max_length=120)
    role: UserRole = UserRole.CUSTOMER


class ProvisionedAccountResponse(BaseModel):
    id: UUID
    email: str
    full_name: str
    #: Only populated outside production, where the logging email sender does
    #: not actually deliver. An invite link is a credential and does not belong
    #: in an API response once real email works.
    invite_url: str | None = None
