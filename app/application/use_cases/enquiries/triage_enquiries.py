"""Open leads, arranged by how soon the client's event is.

The console's dashboard question is not "what arrived most recently" — that is
what the inbox already answers — it is **"what will I regret not having replied
to."** A wedding three weeks away that nobody has touched is urgent; the same
enquiry for next June is not, and sorting by arrival time treats them alike.

The urgency band is computed **here, not in the browser**, for the same reason
`Project.allowed_next_stages` is published rather than inferred: two frontends
that each decide what "this week" means will eventually disagree, and the one
that is wrong will be the one somebody is relying on. It also means "urgent"
has a single definition to change when Cabmora decides it is wrong.
"""

from dataclasses import dataclass
from datetime import date, datetime, timezone
from enum import Enum

from app.domain.entities.enquiry import Enquiry, EnquiryStatus
from app.domain.entities.user import User
from app.domain.repositories.enquiry_repository import EnquiryRepository
from app.domain.repositories.user_repository import UserRepository


class UrgencyBand(str, Enum):
    """How close the event is, as a band rather than a number of days.

    Bands, because the table groups by them and a group heading has to be a
    stable thing to render. The day count travels alongside for the ones that
    want to show "in 9 days".
    """

    #: The event has already happened and the lead is still open. First on the
    #: list because it is the only band that represents a mistake rather than
    #: work: either somebody missed it, or the status was never moved on.
    PASSED = "passed"
    #: Inside a week. Reply today.
    THIS_WEEK = "this_week"
    #: 8–30 days.
    THIS_MONTH = "this_month"
    #: 31–90 days.
    THIS_QUARTER = "this_quarter"
    #: More than 90 days out. Real work, no rush.
    LATER = "later"
    #: No event date on the record. **Not the same as "later"** — we do not know
    #: that it is far away, we know nothing, and the honest thing is to say so
    #: rather than to sort it as though it were distant. The public form only
    #: started asking in October 2026, so every lead before that is in here.
    UNDATED = "undated"


#: The boundaries, in days from today. Named so the one place they are defined
#: is the one place to argue about them.
WITHIN_A_WEEK = 7
WITHIN_A_MONTH = 30
WITHIN_A_QUARTER = 90

#: An open lead this close to its event that nobody has even acknowledged.
NEEDS_CHASING_WITHIN = 14

#: Days a lead may sit untouched before it is a problem on its own.
#:
#: The second source of urgency, and the one that works *today*. Most leads have
#: no event date — the public form only started asking in October 2026 — so a
#: queue that could only measure urgency against the event had nothing to say
#: about almost every row it showed: eleven untouched enquiries, none of them
#: flagged. How long somebody has waited for a reply is always knowable, and a
#: wedding enquiry ignored for nine days has gone to another studio whether or
#: not we know when the wedding is.
#:
#: Two days rather than one: an enquiry that arrives on Saturday evening should
#: not be scolding anybody on Sunday morning.
UNANSWERED_FOR = 2


def band_for(event_date: date | None, *, today: date) -> tuple[UrgencyBand, int | None]:
    """The band and the day count, or `(UNDATED, None)`.

    `today` is passed in rather than read from the clock so the bands are
    testable without freezing time, and so one request cannot straddle midnight
    and put two enquiries in bands computed against different days.
    """
    if event_date is None:
        return UrgencyBand.UNDATED, None
    days = (event_date - today).days
    if days < 0:
        return UrgencyBand.PASSED, days
    if days <= WITHIN_A_WEEK:
        return UrgencyBand.THIS_WEEK, days
    if days <= WITHIN_A_MONTH:
        return UrgencyBand.THIS_MONTH, days
    if days <= WITHIN_A_QUARTER:
        return UrgencyBand.THIS_QUARTER, days
    return UrgencyBand.LATER, days


@dataclass
class TriagedEnquiry:
    enquiry: Enquiry
    band: UrgencyBand
    #: Days until the event; negative once it has passed, null when undated.
    days_until: int | None
    #: How long this has been sitting with us. Always known, which is what makes
    #: it the useful column on the rows that have no event date — and those are
    #: most rows.
    days_waiting: int
    #: Who is working it, resolved for display. Null when nobody has taken it.
    owner_name: str | None
    #: Nobody has acknowledged this and it is either close to its event **or**
    #: has been waiting too long. Two reasons rather than one, because the first
    #: needs a date we usually do not have.
    #:
    #: Derived here so the table does not re-derive "new means untouched" — a
    #: judgement that belongs with the status rules.
    needs_chasing: bool


@dataclass
class Triage:
    items: list[TriagedEnquiry]
    #: Every open lead, not just this page, so a table showing fifty can say
    #: how many it is leaving out.
    open_total: int


class TriageEnquiries:
    def __init__(self, enquiries: EnquiryRepository, users: UserRepository) -> None:
        self._enquiries = enquiries
        self._users = users

    async def execute(
        self, *, actor: User, limit: int = 50, offset: int = 0
    ) -> Triage:
        # `actor` is taken and deliberately not used to filter. Triage is the
        # office's shared queue: a coordinator who only saw their own leads
        # could not pick up an unassigned one, which is most of them. The guard
        # on the route decides who may look at all.
        del actor

        leads = await self._enquiries.list_open_by_event_date(limit=limit, offset=offset)

        # One lookup for the page rather than one per row.
        owners = await self._users.get_many(
            {lead.assigned_to for lead in leads if lead.assigned_to}
        )

        # Read once, outside the loop. See `band_for`.
        today = datetime.now(timezone.utc).date()

        items = []
        for lead in leads:
            when = lead.event_date.date() if lead.event_date else None
            band, days = band_for(when, today=today)
            owner = owners.get(lead.assigned_to) if lead.assigned_to else None
            waiting = (today - lead.created_at.date()).days
            untouched = lead.status is EnquiryStatus.NEW
            items.append(
                TriagedEnquiry(
                    enquiry=lead,
                    band=band,
                    days_until=days,
                    days_waiting=waiting,
                    owner_name=owner.full_name if owner else None,
                    needs_chasing=untouched
                    and (
                        (days is not None and days <= NEEDS_CHASING_WITHIN)
                        or waiting >= UNANSWERED_FOR
                    ),
                )
            )

        return Triage(items=items, open_total=await self._enquiries.count_open())
