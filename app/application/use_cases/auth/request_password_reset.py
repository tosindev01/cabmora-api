"""Ask for a link to choose a new password.

The whole use case is written around one rule: **this endpoint must reveal
nothing about who has an account.** It succeeds identically for an address we
have never seen, one belonging to a suspended account, and one belonging to an
active customer. Anything else turns the sign-in page into a way to test
whether a person is a Cabmora client — which, for a business whose clients are
identifiable from their own wedding photographs, is a disclosure in itself.
"""

import logging

from app.domain.entities.password_reset import PasswordResetToken
from app.domain.entities.user import UserStatus
from app.domain.repositories.password_reset_repository import PasswordResetRepository
from app.domain.repositories.user_repository import UserRepository
from app.domain.services.email_sender import EmailSender

logger = logging.getLogger(__name__)


class RequestPasswordReset:
    def __init__(
        self,
        users: UserRepository,
        tokens: PasswordResetRepository,
        email: EmailSender,
        public_base_url: str,
    ) -> None:
        self._users = users
        self._tokens = tokens
        self._email = email
        self._base_url = public_base_url.rstrip("/")

    async def execute(self, email_address: str) -> None:
        user = await self._users.get_by_email(email_address.strip().lower())

        # Suspended accounts get nothing — their access was revoked, and a
        # reset link would hand it straight back. Everyone else qualifies,
        # including an account whose invite lapsed before it was claimed:
        # that person has no password and no working link, which is precisely
        # the situation this exists to get them out of.
        if user is None or user.status is UserStatus.SUSPENDED:
            # Logged, never returned. Someone typing the wrong address needs
            # support to be able to see that nothing was sent; the person at
            # the keyboard must not be able to tell the difference.
            logger.info(
                "[password-reset] no deliverable account for %s — nothing sent",
                email_address,
            )
            return

        # Retire any link already outstanding, so asking twice does not leave
        # two live ways into the account.
        await self._tokens.invalidate_outstanding(user.id)

        record, token = PasswordResetToken.issue(user.id)
        await self._tokens.add(record)

        await self._email.send_password_reset(
            to=user.email,
            first_name=user.first_name,
            reset_url=f"{self._base_url}/reset-password?token={token}",
        )
