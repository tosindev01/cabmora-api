from abc import ABC, abstractmethod
from uuid import UUID

from app.domain.entities.preferences import UserPreferences


class PreferencesRepository(ABC):
    @abstractmethod
    async def get(self, user_id: UUID) -> UserPreferences:
        """Their preferences, or the defaults.

        Never None. A caller that has to decide what an absent row means is a
        caller that will decide differently from the next one.
        """

    @abstractmethod
    async def save(self, user_id: UUID, preferences: UserPreferences) -> UserPreferences:
        """Insert or update. The row is created on first write."""

    @abstractmethod
    async def get_by_email(self, email: str) -> UserPreferences:
        """Same thing, by address.

        For the send path, which knows who it is writing to only by the address
        on the envelope. Returns the defaults for an address with no account —
        a notice to a non-user is not something a preference can mute.
        """
