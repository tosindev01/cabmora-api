from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from uuid import UUID, uuid4


class MeetingProvider(str, Enum):
    MANUAL = "manual"        # the admin created the call and pasted the link
    GOOGLE_MEET = "google_meet"


class ConsultationStatus(str, Enum):
    """Whether Cabmora has agreed to this time, or only been asked for it.

    A client picking a slot on the website cannot book Cabmora's day. The
    calendar only knows about consultations made through this platform — not
    shoots, not travel, not anything in somebody's own diary — so a slot that
    looks free here may not be. Confirming is what makes it real, and what
    creates the calendar entry and the meeting link.
    """

    #: The client asked for this time. Nothing is in anyone's diary.
    REQUESTED = "requested"
    #: Cabmora agreed it. This is the one with a meeting link.
    CONFIRMED = "confirmed"


@dataclass
class Consultation:
    """A booked call with a prospective client.

    Its own row rather than a couple of columns on the enquiry: calls get moved,
    and the history is signal — "they rescheduled twice" tells you something a
    single `meeting_time` column throws away.
    """

    enquiry_id: UUID
    scheduled_at: datetime
    duration_minutes: int = 30
    #: Defaults to CONFIRMED because an admin booking a call has agreed it by
    #: the act of booking. Only the public form creates a REQUESTED one.
    status: ConsultationStatus = ConsultationStatus.CONFIRMED
    meeting_url: str | None = None
    provider: MeetingProvider = MeetingProvider.MANUAL
    cancelled_at: datetime | None = None
    #: Stamped once a reminder has been attempted. The whole defence against a
    #: cron that runs every few minutes sending the same reminder every time.
    reminder_sent_at: datetime | None = None
    created_by: UUID | None = None
    id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def needs_reminder_at(self, now: datetime, lead_minutes: int) -> bool:
        """Is this call close enough to remind about, and not reminded yet?

        Bounded on both sides. The upper bound is the lead time; the lower bound
        is *now*, because a reminder for a call that already started is noise —
        and without it a missed cron run would eventually fire reminders for
        yesterday.

        A run that is late still sends, just late, rather than skipping the
        reminder entirely — which is why this is a window rather than an exact
        match on the lead time.
        """
        # Never for a call Cabmora has not agreed to. Reminding somebody about
        # an appointment that does not exist yet is worse than silence.
        if not self.is_confirmed:
            return False
        if not self.is_live or self.reminder_sent_at is not None:
            return False
        return now <= self.starts_at <= now + timedelta(minutes=lead_minutes)

    @property
    def is_live(self) -> bool:
        """A cancelled call holds no time. Only live ones can clash.

        A *requested* call is live: two clients must not be able to ask for the
        same slot, and the website should not offer a time somebody is already
        waiting to hear about. Declining it frees the slot again.
        """
        return self.cancelled_at is None

    @property
    def is_confirmed(self) -> bool:
        return self.status is ConsultationStatus.CONFIRMED

    def confirm(self, *, at: datetime | None = None) -> None:
        """Cabmora agrees the call, possibly at a different time.

        Moving it is the same act as agreeing it — an admin looking at a
        requested Thursday who is busy on Thursday says "Friday instead", and
        making that two operations invites the one where the time changes and
        nobody is told.
        """
        self.status = ConsultationStatus.CONFIRMED
        if at is not None:
            self.scheduled_at = at

    @property
    def starts_at(self) -> datetime:
        return _aware(self.scheduled_at)

    @property
    def ends_at(self) -> datetime:
        return self.starts_at + timedelta(minutes=self.duration_minutes)

    def overlaps(self, other: "Consultation") -> bool:
        """Do these two calls share any minute?

        Half-open intervals: a call ending at 10:00 and one starting at 10:00 do
        not clash. Treating them as a clash would make back-to-back slots — the
        normal way anyone books a day — impossible.

        A cancelled call on either side never clashes; the slot is free again.
        """
        if self.id == other.id:
            return False
        if not (self.is_live and other.is_live):
            return False
        return self.starts_at < other.ends_at and other.starts_at < self.ends_at


def _aware(value: datetime) -> datetime:
    """SQLite returns naive datetimes; comparing them to aware ones raises.

    Everything is stored UTC, so an absent tzinfo means UTC rather than local —
    assuming local here would silently shift every booking by an hour for half
    the year.
    """
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
