"""Read and change your own preferences.

Like the rest of `account`, no user id crosses the boundary: the actor is the
subject, so there is no ownership check that could be forgotten.
"""

from dataclasses import dataclass

from app.domain.entities.preferences import NotificationKind, UserPreferences
from app.domain.entities.user import User
from app.domain.repositories.preferences_repository import PreferencesRepository


class GetPreferences:
    def __init__(self, preferences: PreferencesRepository) -> None:
        self._preferences = preferences

    async def execute(self, *, actor: User) -> UserPreferences:
        return await self._preferences.get(actor.id)


@dataclass(frozen=True)
class PreferenceChanges:
    """A patch. `None` means untouched — including `muted`, where an empty set
    is a real instruction ("send me everything") and must not be confused with
    "the client did not mention notifications"."""

    currency: str | None = None
    language: str | None = None
    timezone: str | None = None
    date_format: str | None = None
    muted: set[NotificationKind] | None = None


class UpdatePreferences:
    def __init__(self, preferences: PreferencesRepository) -> None:
        self._preferences = preferences

    async def execute(self, *, actor: User, changes: PreferenceChanges) -> UserPreferences:
        current = await self._preferences.get(actor.id)

        # Rebuilt rather than mutated, so the entity's own validation runs on
        # the whole result — a patch that sets only the currency still proves
        # the rest of the row is a combination the domain accepts.
        updated = UserPreferences(
            currency=changes.currency or current.currency,
            language=changes.language or current.language,
            timezone=changes.timezone or current.timezone,
            date_format=changes.date_format or current.date_format,
            muted=current.muted if changes.muted is None else set(changes.muted),
        )
        return await self._preferences.save(actor.id, updated)
