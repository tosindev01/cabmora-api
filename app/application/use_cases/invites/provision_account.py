from dataclasses import dataclass
from uuid import UUID

from app.core.exceptions import ConfigurationError, EntityAlreadyExistsError
from app.domain.entities.invite import InviteToken
from app.domain.entities.user import User, UserRole, UserStatus
from app.domain.repositories.invite_repository import InviteRepository
from app.domain.repositories.user_repository import UserRepository
from app.domain.services.email_sender import EmailSender


#: Where each kind of account goes to choose its password.
#:
#: Staff land on the admin console and everybody else on the public site,
#: because the session cookie is scoped to the host that sets it: a
#: coordinator who chose a password on the studio site would arrive at the
#: console signed out, on a marketing page, with nothing telling them that
#: the screens they were hired to use are on a different address.
#:
#: Creators go to Flow's own page rather than the studio's for the same reason
#: in reverse — a new partner sent to a page branded for somebody else's
#: product wonders what they have joined.
INVITE_PATHS: dict[UserRole, str] = {
    UserRole.CUSTOMER: "/accept-invite",
    UserRole.CREATOR: "/flow/setup-password",
    UserRole.COORDINATOR: "/accept-invite",
    UserRole.ADMIN: "/accept-invite",
}

#: The roles whose invite belongs on the console rather than the public site.
CONSOLE_ROLES = frozenset({UserRole.COORDINATOR, UserRole.ADMIN})


@dataclass
class ProvisionedAccount:
    user: User
    #: The plaintext invite link. Returned once, for the caller to decide
    #: whether to surface it; it cannot be recovered afterwards.
    invite_url: str


class ProvisionAccount:
    """Create an account for somebody who has not signed up, and invite them in.

    Two callers, one mechanism: an admin adding a customer who booked over the
    phone, and an approved Flow creator. Both need an account that exists but
    has no password, and a single-use link so the person chooses their own —
    which is the whole reason this is not "admin types a temporary password
    and reads it out".

    The account is ACTIVE, not PENDING: the point of the acceptance queue is to
    vet strangers, and somebody an admin created or an application we approved
    has already been vetted. Leaving it pending would mean approving our own
    action twice.

    Where the link points is decided from the role, by `INVITE_PATHS` and
    `CONSOLE_ROLES` — not by the caller. Four audiences now have three front
    doors between them, and a caller that has to remember which one is a
    caller that will eventually email a coordinator a link to the marketing
    site.
    """

    def __init__(
        self,
        users: UserRepository,
        invites: InviteRepository,
        email: EmailSender,
        invite_base_url: str,
        console_base_url: str | None = None,
    ) -> None:
        self._users = users
        self._invites = invites
        self._email = email
        self._invite_base_url = invite_base_url.rstrip("/")
        self._console_base_url = (console_base_url or "").rstrip("/") or None

    def _invite_url(self, role: UserRole, token: str) -> str:
        if role in CONSOLE_ROLES:
            if self._console_base_url is None:
                # Refused rather than quietly sent to the public site. A staff
                # invite that lands on the wrong host produces an account that
                # exists, a token that is spent, and a person who cannot get
                # in — and the single-use link cannot be reissued.
                raise ConfigurationError(
                    "ADMIN_BASE_URL must be set before staff accounts can be invited"
                )
            base = self._console_base_url
        else:
            base = self._invite_base_url
        return f"{base}{INVITE_PATHS[role]}?token={token}"

    async def execute(
        self,
        email: str,
        first_name: str,
        last_name: str,
        *,
        role: UserRole = UserRole.CUSTOMER,
        phone: str | None = None,
        whatsapp: str | None = None,
    ) -> ProvisionedAccount:
        # Before the account, so a misconfigured console does not leave a user
        # row and a spent token behind.
        if role in CONSOLE_ROLES and self._console_base_url is None:
            raise ConfigurationError(
                "ADMIN_BASE_URL must be set before staff accounts can be invited"
            )
        if await self._users.get_by_email(email.lower()) is not None:
            raise EntityAlreadyExistsError("An account with this email already exists")

        user = await self._users.add(
            User(
                email=email.lower(),
                first_name=first_name.strip(),
                last_name=last_name.strip(),
                hashed_password=None,
                phone=phone,
                whatsapp=whatsapp,
                role=role,
                status=UserStatus.ACTIVE,
            )
        )

        record, token = InviteToken.issue(user.id)
        await self._invites.add(record)
        invite_url = self._invite_url(role, token)

        await self._email.send_invite(
            to=user.email, first_name=user.first_name, invite_url=invite_url
        )
        return ProvisionedAccount(user=user, invite_url=invite_url)
