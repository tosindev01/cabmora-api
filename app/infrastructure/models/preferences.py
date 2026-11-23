from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.entities.preferences import NotificationKind, UserPreferences
from app.infrastructure.database import Base


class UserPreferencesModel(Base):
    """One row per account, written on first change.

    `muted` is a comma-separated list rather than a child table, and that is a
    considered exception to the pattern used for permissions. A permission is
    asked about across accounts — "who can see payments?" is a real query. A
    mute is only ever read for one person, on the way to sending them one
    email, so a join table would buy a query nobody runs.
    """

    __tablename__ = "user_preferences"

    user_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    currency: Mapped[str] = mapped_column(String(3), default="GBP")
    language: Mapped[str] = mapped_column(String(10), default="en-GB")
    timezone: Mapped[str] = mapped_column(String(64), default="Europe/London")
    date_format: Mapped[str] = mapped_column(String(12), default="DD/MM/YYYY")
    muted: Mapped[str] = mapped_column(Text, default="")

    def to_entity(self) -> UserPreferences:
        return UserPreferences(
            currency=self.currency,
            language=self.language,
            timezone=self.timezone,
            date_format=self.date_format,
            # Unknown values are dropped rather than raising: a kind removed in
            # a later version would otherwise make this person's settings page
            # fail to load, over a preference that no longer means anything.
            muted={
                NotificationKind(value)
                for value in filter(None, (self.muted or "").split(","))
                if value in NotificationKind._value2member_map_
            },
        )

    def apply(self, preferences: UserPreferences) -> None:
        self.currency = preferences.currency
        self.language = preferences.language
        self.timezone = preferences.timezone
        self.date_format = preferences.date_format
        # Sorted so the column is stable — an unordered set would rewrite the
        # row on every save and make a diff of the table meaningless.
        self.muted = ",".join(sorted(kind.value for kind in preferences.muted))
