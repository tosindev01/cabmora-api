from datetime import datetime
from uuid import UUID

from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.domain.entities.preferences import NotificationKind
from app.domain.entities.user import Permission, UserRole, UserStatus


class RegisterRequest(BaseModel):
    email: EmailStr
    first_name: str = Field(min_length=1, max_length=120)
    last_name: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=8, max_length=128)
    # A two-value Literal, deliberately NOT `UserRole`. This is public input;
    # accepting a role would let anyone register themselves as an admin. With
    # only these two spellings accepted, that is unreachable by construction.
    account_type: Literal["customer", "creator"] = "customer"
    # Deliberately no `confirm_password`. The server cannot verify anything the
    # client cannot — a buggy or hostile client simply sends the same string
    # twice — so it would only put the secret on the wire and into request logs
    # a second time. The confirm field is validated in the browser.


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class UserResponse(BaseModel):
    id: UUID
    email: str
    first_name: str
    last_name: str
    # Sent alongside the parts so neither frontend has to concatenate, and so
    # display code that already reads `full_name` keeps working.
    full_name: str
    #: How to reach them. Null for anyone who never gave a number — most
    #: accounts, since only the enquiry form asks for one today.
    phone: str | None = None
    whatsapp: str | None = None
    #: A signed URL that expires, minted per response — never a stored value.
    #: Null when no picture has been uploaded, or when storage is unconfigured.
    avatar_url: str | None = None
    role: UserRole
    status: UserStatus
    #: Sections granted on top of the role. Empty for almost everybody.
    granted: list[Permission] = Field(default_factory=list)
    #: What this person's groups give them, kept apart from `granted` so the
    #: console can say where each permission came from.
    from_groups: list[Permission] = Field(default_factory=list)
    #: Names of those groups, for display beside what they give.
    group_names: list[str] = Field(default_factory=list)
    #: Everything this account can actually open, role and grants combined.
    #: Published so the console draws from the same answer the guards use
    #: rather than inferring it from the role a second time.
    reachable: list[Permission] = Field(default_factory=list)
    #: Where this person's work actually is, when it is not on the app they are
    #: looking at. The admin console is a separate application on its own
    #: origin, so the public site cannot route to it — it has to be told, and
    #: only the API knows the address.
    #:
    #: Non-null only for staff. A customer is never handed the console's
    #: hostname, because a customer has no business being sent there.
    console_url: str | None = None
    created_at: datetime


class TokenResponse(BaseModel):
    access_token: str
    token_type: str
    user: UserResponse


class AcceptInviteRequest(BaseModel):
    token: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=8, max_length=128)


class ForgotPasswordRequest(BaseModel):
    # Not `EmailStr`. A rejected address would answer "that is not a real
    # email" for one input and 204 for another, which is the enumeration this
    # endpoint exists to avoid — and an address that cannot exist simply
    # matches no account.
    email: str = Field(min_length=3, max_length=320)


class ResetPasswordRequest(BaseModel):
    token: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=8, max_length=128)


class ProfileUpdateRequest(BaseModel):
    """Every field optional: this is a patch, and an omitted field is untouched.

    An empty string on `phone` or `whatsapp` clears it, which is why they are
    not simply trimmed away — "" and absent mean different things.

    Deliberately no `email`. The address is the login and the destination for
    every reset and invite, so moving it is an administrative act. Leaving the
    field out of the schema means an email sent here is rejected rather than
    quietly ignored, which is the difference between a rule and a hidden form
    field.
    """

    model_config = ConfigDict(extra="forbid")

    first_name: str | None = Field(default=None, max_length=120)
    last_name: str | None = Field(default=None, max_length=120)
    phone: str | None = Field(default=None, max_length=50)
    whatsapp: str | None = Field(default=None, max_length=50)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1)
    new_password: str = Field(min_length=8, max_length=128)


class AvatarUploadRequest(BaseModel):
    #: Hex digest the browser computed over the file. The key is derived from
    #: it, so the same picture uploaded twice occupies one object.
    content_hash: str = Field(min_length=16, max_length=128)
    content_type: str
    byte_size: int = Field(gt=0)


class AvatarUploadResponse(BaseModel):
    key: str
    upload_id: str
    part_size: int
    part_urls: list[str]


class AvatarConfirmRequest(BaseModel):
    content_hash: str = Field(min_length=16, max_length=128)
    upload_id: str
    #: In part order. The provider reassembles by position, so a shuffled list
    #: yields a corrupt object rather than an error.
    etags: list[str] = Field(min_length=1)


class PreferencesResponse(BaseModel):
    currency: str
    language: str
    timezone: str
    date_format: str
    #: What they have turned off. Everything else they receive.
    muted: list[NotificationKind]
    #: Published so the settings screen offers exactly what the server accepts,
    #: rather than keeping its own copy of the list that drifts.
    available_currencies: list[str]
    available_languages: list[str]
    available_date_formats: list[str]
    mutable_notifications: list[NotificationKind]


class PreferencesUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    currency: str | None = None
    language: str | None = None
    timezone: str | None = Field(default=None, max_length=64)
    date_format: str | None = None
    #: Absent leaves notifications alone; `[]` means "send me everything".
    muted: list[NotificationKind] | None = None
