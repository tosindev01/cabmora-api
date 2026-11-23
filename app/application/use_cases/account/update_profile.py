"""Let someone edit their own details.

Their own, and nobody else's: there is no `user_id` parameter here. A use case
that took one would need an ownership check, and the check is the kind of thing
that gets forgotten in the next endpoint that calls it. The actor *is* the
subject, so the question cannot arise.
"""

from dataclasses import dataclass

from app.core.exceptions import ValidationError
from app.domain.entities.user import User
from app.domain.repositories.user_repository import UserRepository


@dataclass(frozen=True)
class ProfileChanges:
    """Only what was sent. `None` means "leave it alone", which is not the same
    as clearing a field — clearing a phone number is an empty string.

    No email. The address is the login, it is what password resets and invites
    are sent to, and it is how a project's client is recognised — letting the
    account holder move it silently re-points all of that. Changing it is an
    administrative act, not a profile edit.
    """

    first_name: str | None = None
    last_name: str | None = None
    phone: str | None = None
    whatsapp: str | None = None


def _trimmed(value: str | None) -> str | None:
    if value is None:
        return None
    return value.strip()


class UpdateProfile:
    def __init__(self, users: UserRepository) -> None:
        self._users = users

    async def execute(self, *, actor: User, changes: ProfileChanges) -> User:
        first_name = _trimmed(changes.first_name)
        last_name = _trimmed(changes.last_name)

        if first_name is not None and not first_name:
            raise ValidationError("A first name is needed.")
        if last_name is not None and not last_name:
            raise ValidationError("A last name is needed.")

        if first_name is not None:
            actor.first_name = first_name
        if last_name is not None:
            actor.last_name = last_name

        # An empty string clears these; they are genuinely optional.
        if changes.phone is not None:
            actor.phone = _trimmed(changes.phone) or None
        if changes.whatsapp is not None:
            actor.whatsapp = _trimmed(changes.whatsapp) or None

        return await self._users.save_profile(actor)
