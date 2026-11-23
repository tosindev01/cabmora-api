"""The times a visitor may ask for, from the public website.

Deliberately not the inverse of `ListAvailability`. That one answers "what is
booked, and who with" for an admin looking at their week. This one answers
"what may I ask for" for a stranger, and the difference is not cosmetic:

* It returns **free** slots, never busy ones. A caller cannot tell whether
  Thursday at three is booked, outside working hours, or a bank holiday — all
  three come back the same way, which is nobody's business but Cabmora's.
* It carries no names, no event types and no ids. There is nothing in the
  response to leak, rather than a response that happens not to leak today.

The hours are policy and they live here, in one place, rather than being
re-derived by each frontend that draws a calendar.
"""

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from app.core.exceptions import ValidationError
from app.domain.repositories.enquiry_repository import EnquiryRepository

#: The studio is in Manchester and its clients think in local time. Slots are
#: generated in this zone and returned as UTC instants.
STUDIO_TZ = ZoneInfo("Europe/London")

#: Working hours, local. A consultation offered at 8pm would be answered by
#: nobody.
OPEN_HOUR = 9
CLOSE_HOUR = 17

#: How long a consultation takes, and therefore the grid a client picks from.
SLOT_MINUTES = 30

#: Nothing sooner than this. Zero by decision on 2026-09-30: every day should
#: be offered, and a client who wants to talk this afternoon should be able to
#: ask. A slot that has already started is still excluded, which is arithmetic
#: rather than policy.
MIN_NOTICE_HOURS = 0

#: How far out to offer. Beyond this a date is a guess rather than a plan.
MAX_HORIZON_DAYS = 60

#: A window wider than this is a report, not a booking view.
MAX_WINDOW_DAYS = 31

#: Slack on that limit, and it is not arbitrary.
#:
#: A caller asking for "this month" sends local midnight to local midnight.
#: In a timezone that changes its clocks mid-month that span is 31 days and
#: an hour — one hour over — so every visitor in the UK was refused the whole
#: of October and shown a calendar with nothing on it, while a visitor an hour
#: east saw the same month as normal. A day of slack keeps the limit's intent
#: (this is not a reporting endpoint) without making it a trap that springs
#: twice a year.
WINDOW_SLACK = timedelta(days=1)


class ListOpenSlots:
    def __init__(self, enquiries: EnquiryRepository) -> None:
        self._enquiries = enquiries

    async def execute(self, *, start: datetime, end: datetime) -> list[datetime]:
        if end <= start:
            raise ValidationError("The window must end after it starts.")
        if end - start > timedelta(days=MAX_WINDOW_DAYS) + WINDOW_SLACK:
            raise ValidationError(f"Ask for at most {MAX_WINDOW_DAYS} days at a time.")

        now = datetime.now(timezone.utc)
        earliest = now + timedelta(hours=MIN_NOTICE_HOURS)
        latest = now + timedelta(days=MAX_HORIZON_DAYS)

        # The half hour, not the day. A 9am call takes 9am off the calendar
        # and leaves the rest of the Thursday bookable — two clients wanting
        # the third of the month is two bookings, not a collision.
        #
        # Requested counts as taken. Two people must not be able to ask for
        # the same slot, and one somebody is waiting to hear about is not one
        # to offer somebody else.
        taken = [
            c
            for c in await self._enquiries.list_consultations_between(start, end)
            if c.is_live
        ]

        open_slots: list[datetime] = []
        for moment in _candidates(start, end):
            if not (earliest <= moment <= latest):
                continue
            finish = moment + timedelta(minutes=SLOT_MINUTES)
            # Half-open, so a call ending at 10:00 does not block 10:00.
            if any(c.starts_at < finish and moment < c.ends_at for c in taken):
                continue
            open_slots.append(moment)
        return open_slots


def _candidates(start: datetime, end: datetime):
    """Every working-hours slot in the window, as UTC instants.

    Built day by day in the studio's own timezone rather than by adding thirty
    minutes to a UTC cursor: the clocks change twice a year, and a UTC grid
    would silently serve 8am and 4pm slots for half of it.
    """
    day = start.astimezone(STUDIO_TZ).date()
    last = end.astimezone(STUDIO_TZ).date()

    while day <= last:
        # Every day, weekends included. Couples planning a wedding often
        # cannot talk on a Tuesday afternoon.
        cursor = _local(day, OPEN_HOUR)
        close = _local(day, CLOSE_HOUR)
        while cursor + timedelta(minutes=SLOT_MINUTES) <= close:
            moment = cursor.astimezone(timezone.utc)
            if start <= moment < end:
                yield moment
            cursor += timedelta(minutes=SLOT_MINUTES)
        day += timedelta(days=1)


def _local(day: date, hour: int) -> datetime:
    return datetime.combine(day, time(hour=hour), tzinfo=STUDIO_TZ)

