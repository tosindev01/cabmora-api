from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime

from app.domain.entities.consultation import MeetingProvider


@dataclass(frozen=True)
class ScheduledMeeting:
    url: str | None
    provider: MeetingProvider


class MeetingScheduler(ABC):
    """Creating a video call, as an interface the application depends on.

    Two adapters: `ManualScheduler` records a link an admin pasted, and
    `GoogleCalendarScheduler` creates the call in Cabmora's own calendar.
    `get_meeting_scheduler` chooses between them and no use case can tell which
    it got — the same seam as `EmailSender`.

    The Google path costs an OAuth consent flow and a stored refresh token, a
    security surface of its own. What it buys is not saving the admin a tab: it
    is that the booking exists somewhere other than our database. A call the
    calendar has never heard of is invisible to everyone not looking at the
    admin console.
    """

    @abstractmethod
    async def schedule(
        self,
        *,
        summary: str,
        starts_at: datetime,
        minutes: int,
        attendees: list[str],
        meeting_url: str | None = None,
    ) -> ScheduledMeeting:
        """Return the call's details, creating it if this backend can."""


class SchedulerAuthExpired(RuntimeError):
    """The scheduler's saved sign-in is no longer accepted.

    Declared beside the port rather than inside the Google adapter so a use
    case can tell "this needs a person" from "the calendar had a bad minute"
    without importing infrastructure. Any future backend with a credential
    that can lapse raises the same thing.
    """


class ManualScheduler(MeetingScheduler):
    """Records a call the admin created themselves.

    `meeting_url` is passed straight through: this backend does not invent a
    link, so if the admin has not pasted one the consultation is booked without
    it rather than with something fabricated.
    """

    async def schedule(
        self,
        *,
        summary: str,
        starts_at: datetime,
        minutes: int,
        attendees: list[str],
        meeting_url: str | None = None,
    ) -> ScheduledMeeting:
        return ScheduledMeeting(url=meeting_url, provider=MeetingProvider.MANUAL)
