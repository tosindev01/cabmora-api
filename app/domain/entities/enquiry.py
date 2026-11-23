from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from uuid import UUID, uuid4


class EnquiryStatus(str, Enum):
    """The lead pipeline.

    `WON`/`LOST` rather than `converted`/`closed`: the reporting question is
    always "what is our win rate", and `closed` cannot answer it — it reads as
    either outcome depending on who is looking.
    """

    NEW = "new"
    CONTACTED = "contacted"
    CONSULTATION_BOOKED = "consultation_booked"
    QUOTED = "quoted"
    WON = "won"    # became a project
    LOST = "lost"  # did not


#: Every live stage can go to LOST — a lead dies at any point, and a pipeline
#: that cannot say so accumulates stale rows nobody will admit are dead.
#:
#: WON is terminal because a project exists downstream; unwinding it would
#: orphan real work. LOST is not: leads come back.
ALLOWED_TRANSITIONS: dict[EnquiryStatus, set[EnquiryStatus]] = {
    EnquiryStatus.NEW: {
        EnquiryStatus.CONTACTED,
        # Booking a call *is* contact. Without this edge a lead with a
        # consultation in the diary tomorrow sits on the board looking as
        # untouched as one nobody has read yet.
        EnquiryStatus.CONSULTATION_BOOKED,
        EnquiryStatus.LOST,
    },
    EnquiryStatus.CONTACTED: {
        EnquiryStatus.CONSULTATION_BOOKED,
        EnquiryStatus.QUOTED,
        EnquiryStatus.LOST,
    },
    EnquiryStatus.CONSULTATION_BOOKED: {
        EnquiryStatus.QUOTED,
        EnquiryStatus.CONTACTED,
        EnquiryStatus.LOST,
    },
    EnquiryStatus.QUOTED: {
        EnquiryStatus.WON,
        EnquiryStatus.LOST,
        EnquiryStatus.CONTACTED,
    },
    EnquiryStatus.WON: set(),
    EnquiryStatus.LOST: {EnquiryStatus.CONTACTED},
}

#: Stages that still count as being worked, for "open pipeline" counts.
OPEN_STATUSES = {
    EnquiryStatus.NEW,
    EnquiryStatus.CONTACTED,
    EnquiryStatus.CONSULTATION_BOOKED,
    EnquiryStatus.QUOTED,
}


@dataclass
class Enquiry:
    #: Stored apart, like `User`, rather than as one `name` column.
    #: `full_name.split()[0]` was how the acknowledgement email found a first
    #: name, which gets "Mary" out of "Mary Jane Smith" and is wrong.
    first_name: str
    last_name: str
    email: str
    event_type: str  # wedding, birthday, business event, graduation...
    message: str
    phone: str | None = None
    #: A separate number, because the one people answer is often not the one
    #: they give. Optional: asking for two numbers to send one enquiry is how
    #: a form loses people.
    whatsapp: str | None = None
    event_date: datetime | None = None
    #: When the work is due. Cabmora's own field, not the client's — it is
    #: agreed on the call and carries to the project on conversion, so the
    #: date nobody has to re-type is the one everybody already agreed.
    deadline: datetime | None = None
    status: EnquiryStatus = EnquiryStatus.NEW

    #: The admin working this lead.
    assigned_to: UUID | None = None
    #: Set when the enquirer has an account — on conversion, or if their address
    #: already matched one.
    customer_id: UUID | None = None
    #: What this became. Without it, "where did this project come from?" has no
    #: answer once the enquiry is won.
    converted_project_id: UUID | None = None

    #: Integer minor units, as a range. Free text ("$5–8k") cannot be reported
    #: on; a single figure forces a precision clients rarely give this early.
    budget_min_minor: int | None = None
    budget_max_minor: int | None = None

    id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def full_name(self) -> str:
        """Derived, never stored — one name in one place cannot disagree."""
        return f"{self.first_name} {self.last_name}".strip()

    @property
    def is_open(self) -> bool:
        return self.status in OPEN_STATUSES

    def can_move_to(self, status: EnquiryStatus) -> bool:
        return status in ALLOWED_TRANSITIONS[self.status]

    @property
    def allowed_next_statuses(self) -> list["EnquiryStatus"]:
        """Published to the client so a status control offers only legal moves,
        derived from the same map that enforces them."""
        allowed = ALLOWED_TRANSITIONS[self.status]
        return [status for status in EnquiryStatus if status in allowed]
