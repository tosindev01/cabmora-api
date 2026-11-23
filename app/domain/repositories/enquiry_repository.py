from abc import ABC, abstractmethod
from datetime import datetime
from uuid import UUID

from app.domain.entities.consultation import Consultation
from app.domain.entities.enquiry import Enquiry, EnquiryStatus
from app.domain.entities.enquiry_event import EnquiryEvent


class EnquiryRepository(ABC):
    @abstractmethod
    async def add(self, enquiry: Enquiry, event: EnquiryEvent) -> Enquiry:
        """Create an enquiry and its RECEIVED event in one transaction."""

    @abstractmethod
    async def get_by_id(self, enquiry_id: UUID) -> Enquiry | None: ...

    @abstractmethod
    async def update(self, enquiry: Enquiry, event: EnquiryEvent | None = None) -> Enquiry: ...

    @abstractmethod
    async def list_all(
        self,
        limit: int = 30,
        offset: int = 0,
        status: EnquiryStatus | None = None,
        assigned_to: UUID | None = None,
        search: str | None = None,
    ) -> list[Enquiry]: ...

    @abstractmethod
    async def list_open_by_event_date(
        self, *, limit: int = 50, offset: int = 0
    ) -> list[Enquiry]:
        """Open leads, soonest event first, for the console's triage table.

        Its own method rather than an `order_by` argument on `list_all`: the
        ordering is not a preference, it is the whole point of the query, and it
        carries two rules that a caller must not be able to get wrong —

        · **Open only.** A won or lost lead is finished; padding a work queue
          with rows nobody can act on is how a queue stops being read.
        · **Undated last, never first.** `event_date` is nullable and Postgres
          and SQLite disagree about where NULLs sort, so the ordering is stated
          explicitly. An enquiry with no date is the least urgent thing on the
          list, not the most.
        """

    @abstractmethod
    async def count_open(self) -> int:
        """How many open leads there are in total, so a table showing the first
        fifty can say what it is not showing."""

    @abstractmethod
    async def count_all(
        self,
        status: EnquiryStatus | None = None,
        assigned_to: UUID | None = None,
        search: str | None = None,
    ) -> int: ...

    @abstractmethod
    async def list_events(self, enquiry_id: UUID) -> list[EnquiryEvent]: ...

    @abstractmethod
    async def add_event(self, event: EnquiryEvent) -> EnquiryEvent: ...

    @abstractmethod
    async def add_consultation(self, consultation: Consultation) -> Consultation: ...

    @abstractmethod
    async def list_consultations(self, enquiry_id: UUID) -> list[Consultation]: ...

    @abstractmethod
    async def list_consultations_between(
        self, start: datetime, end: datetime
    ) -> list[Consultation]:
        """Every live consultation touching the window, across all enquiries.

        Serves two callers that must agree: the availability grid an admin looks
        at, and the clash check that refuses a booking. Two queries here would
        eventually disagree and let a double-booking through the very screen
        built to prevent it.

        Cancelled calls are excluded — their slot is free.
        """

    @abstractmethod
    async def get_consultation(self, consultation_id: UUID) -> Consultation | None: ...

    @abstractmethod
    async def update_consultation(self, consultation: Consultation) -> Consultation:
        """Write back a call whose time, status or link has changed.

        Distinct from `mark_reminder_sent`, which touches one column and is
        called by a cron. This one carries the whole thing, because confirming
        a requested slot changes four fields at once and writing three of them
        would leave a call that is agreed but has no link.
        """

    @abstractmethod
    async def list_consultations_awaiting_reminder(
        self, now: datetime, lead_minutes: int
    ) -> list[Consultation]:
        """Live, un-reminded calls starting within the lead time.

        Bounded below by `now` as well as above: a reminder for a call that
        already started is noise, and without the lower bound a cron that was
        down overnight would wake up and remind everyone about yesterday.
        """

    @abstractmethod
    async def mark_reminder_sent(self, consultation_id: UUID, at: datetime) -> None:
        """Stamp a consultation so the next run skips it."""
