from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field


class CreatorApplicationRequest(BaseModel):
    """What the Flow application form sends.

    The survey answers are length-capped strings rather than enums, matching
    the domain: they are options on a marketing page and will change with it.
    Capping the length is the part that matters — this endpoint is public.
    """

    studio_name: str = Field(min_length=1, max_length=255)
    applicant_name: str = Field(min_length=1, max_length=255)
    email: EmailStr
    portfolio_url: str | None = Field(default=None, max_length=500)
    discipline: str = Field(default="", max_length=60)
    annual_volume: str = Field(default="", max_length=60)
    storage_needs: str = Field(default="", max_length=60)
    bottleneck: str = Field(default="", max_length=60)
    plan: str = Field(default="", max_length=60)


class CreatorApplicationResponse(BaseModel):
    """What a public applicant gets back.

    Deliberately thin: an id and a status, and nothing about who reviewed it
    or why. The decision note is for the team.
    """

    id: UUID
    studio_name: str
    status: str
    created_at: datetime


class AdminCreatorApplicationResponse(CreatorApplicationResponse):
    """The same application as the review queue sees it."""

    applicant_name: str
    email: str
    portfolio_url: str | None
    discipline: str
    annual_volume: str
    storage_needs: str
    bottleneck: str
    plan: str
    decision_note: str | None
    reviewed_by: UUID | None
    reviewed_at: datetime | None
    created_user_id: UUID | None


class DeclineRequest(BaseModel):
    #: Why. Optional, and never sent to the applicant — the decline email is
    #: deliberately the same for everyone, because a one-line reason written
    #: in a hurry reads worse than none.
    note: str | None = Field(default=None, max_length=2000)


class ApprovalResponse(BaseModel):
    application: AdminCreatorApplicationResponse
    #: Shown once so an admin can pass it on if the email failed — and only
    #: outside deployment. This link sets a password on a real account, so
    #: production never puts one in an API response, matching how invites are
    #: already handled.
    setup_url: str | None = None
