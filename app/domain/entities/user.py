from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from uuid import UUID, uuid4


class UserStatus(str, Enum):
    """Three states, because two cannot express this.

    A PENDING user must be able to sign in — they need a session to see the
    "awaiting acceptance" screen at all — while a SUSPENDED user must not.
    A single `is_active` boolean collapses those into one another.
    """

    PENDING = "pending"      # registered, awaiting acceptance
    ACTIVE = "active"        # accepted; full access
    SUSPENDED = "suspended"  # access revoked


class UserRole(str, Enum):
    CUSTOMER = "customer"
    CREATOR = "creator"  # partner photographer/videographer
    #: Cabmora's own staff, scoped to the shoots they are put on. Runs the
    #: sales pipeline and the projects they are a member of; cannot reach
    #: people, money, or who joins the platform. The role exists because
    #: "everyone with a login sees every client's wedding photographs" is not
    #: a defensible position for a business holding images of identifiable
    #: people.
    COORDINATOR = "coordinator"
    ADMIN = "admin"


class Permission(str, Enum):
    """A section of the console somebody may be let into.

    Coarse on purpose — one per sidebar entry. Finer grain ("may refund but
    not issue") is a different feature and a worse first version: nobody holds
    a twenty-row matrix in their head, so it gets set once and never audited.
    """

    PROJECTS = "projects"
    ENQUIRIES = "enquiries"
    PAYMENTS = "payments"
    REVIEWS = "reviews"
    CREATOR_APPLICATIONS = "creator_applications"
    REPORTS = "reports"
    USERS = "users"
    TEAM = "team"
    SETTINGS = "settings"


#: What every coordinator reaches without being granted anything.
COORDINATOR_BASELINE = frozenset({Permission.PROJECTS, Permission.ENQUIRIES})

#: What an administrator may hand out. The three that are missing are missing
#: deliberately, and each would be an escalation rather than a convenience:
#:
#: * TEAM — `PUT /projects/{id}/members` is admin-only because a coordinator
#:   who can add themselves to a project can reach every client in the system.
#: * USERS — user management changes roles, so it is a two-click promotion to
#:   administrator and a ladder out of this whole mechanism.
#: * SETTINGS — platform settings decide delivery and payment behaviour for
#:   every project at once.
#:
#: Enforced here rather than in the console: a list the UI merely declines to
#: draw is a list somebody can still POST.
GRANTABLE = frozenset(
    {
        Permission.PAYMENTS,
        Permission.REVIEWS,
        Permission.CREATOR_APPLICATIONS,
        Permission.REPORTS,
    }
)


@dataclass
class User:
    email: str
    first_name: str
    last_name: str
    #: None until the account is claimed. An admin can create a customer so
    #: they do not have to sign up; that account exists but cannot be signed
    #: into until the invite is accepted.
    hashed_password: str | None
    #: How to reach them. Collected on the enquiry and copied here at
    #: conversion: the number belongs to the person, not to the one form they
    #: filled in, and a client who signed up directly never had an enquiry at
    #: all. Before this, a project's client had no reachable phone number
    #: anywhere in the system.
    phone: str | None = None
    whatsapp: str | None = None
    #: The object key of their profile picture, never a URL. Download URLs are
    #: presigned and expire in minutes, so a stored one is a dead link by the
    #: time anybody reads the row.
    avatar_key: str | None = None
    #: The payment gateway's id for this person, once they have been given
    #: one. Only customers ever acquire it, and only on their first bank
    #: transfer — a card payment needs no customer, so most accounts keep this
    #: null for ever. Stored rather than looked up each time because the
    #: account number the client is told to pay into belongs to it: losing the
    #: id means issuing them a second account and splitting their money across
    #: two.
    stripe_customer_id: str | None = None
    role: UserRole = UserRole.CUSTOMER
    status: UserStatus = UserStatus.ACTIVE
    #: Sections this person has been let into on top of their role. Hydrated
    #: by the repository from its own table, like a project's members.
    #:
    #: Additive only. A grant that could also take something away would mean
    #: two sources of truth arguing, and "why can Devon not see Projects"
    #: becomes a puzzle instead of a fact.
    granted: set[Permission] = field(default_factory=set)
    #: What the groups this person is in give them. Kept apart from `granted`
    #: rather than merged, because the console has to say where each
    #: permission came from: an admin who unticks one and watches it stay on
    #: because a group still provides it is looking at what reads as a bug.
    from_groups: set[Permission] = field(default_factory=set)
    #: Names of those groups, for display beside the permissions they give.
    group_names: list[str] = field(default_factory=list)
    id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def can_authenticate(self) -> bool:
        """Suspension ends a session; awaiting acceptance does not.

        An unclaimed account has no password and so cannot be signed into at
        all — checked here rather than left to `verify_password`, which would
        be asked to compare against None.
        """
        return self.status is not UserStatus.SUSPENDED and self.hashed_password is not None

    def can(self, permission: Permission) -> bool:
        """Whether this account may use a section of the console.

        One answer, read by the guards and published to the console, so the
        menu and the API cannot disagree about what a door does.
        """
        if self.role is UserRole.ADMIN:
            return True
        # Console permissions mean nothing outside the console. A customer
        # holding one would be a row that looks like access and is not, so
        # the question is answered before the grants are consulted.
        if self.role is not UserRole.COORDINATOR:
            return False
        return (
            permission in COORDINATOR_BASELINE
            or permission in self.granted
            or permission in self.from_groups
        )

    @property
    def reachable(self) -> set[Permission]:
        """Everything this account can open. For display, not for guarding."""
        return {p for p in Permission if self.can(p)}

    @property
    def full_name(self) -> str:
        """Display name, derived rather than stored.

        Two frontends render a user's name. If the whole were a column
        alongside the parts, an update touching one and not the other would
        leave them silently disagreeing; deriving it means there is nothing
        to keep in sync.
        """
        return f"{self.first_name} {self.last_name}".strip()
