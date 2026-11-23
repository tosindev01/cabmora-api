from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import UUID, uuid4


class EnquiryEventKind(str, Enum):
    RECEIVED = "received"
    ASSIGNED = "assigned"
    STATUS_CHANGED = "status_changed"
    NOTE_ADDED = "note_added"
    #: Staff corrected a date. Recorded rather than silent: what the client
    #: submitted is evidence, and a record that can be quietly tidied is not
    #: one — so the change is allowed and the old value is kept here.
    DETAILS_CHANGED = "details_changed"
    #: The visitor asked for a time from the website. Distinct from BOOKED:
    #: the timeline should show that the client chose it and Cabmora agreed,
    #: not just that a call appeared in the diary.
    CONSULTATION_REQUESTED = "consultation_requested"
    CONSULTATION_BOOKED = "consultation_booked"
    CONSULTATION_CANCELLED = "consultation_cancelled"
    WON = "won"
    LOST = "lost"


@dataclass(frozen=True)
class EnquiryEvent:
    """Append-only history of a lead.

    Same shape as `ProjectEvent`, and deliberately so: on conversion these seed
    the new project's timeline, so a client's history starts at first contact
    rather than at the moment someone pressed "create project".

    Frozen — an editable event is not a record of what happened.
    """

    enquiry_id: UUID
    kind: EnquiryEventKind
    actor_id: UUID | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    id: UUID = field(default_factory=uuid4)
    occurred_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
