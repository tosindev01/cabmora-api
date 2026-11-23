from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from app.domain.entities.consultation import ConsultationStatus, MeetingProvider
from app.application.use_cases.enquiries.triage_enquiries import UrgencyBand
from app.domain.entities.enquiry import EnquiryStatus
from app.domain.entities.enquiry_event import EnquiryEventKind


class EnquiryUpdateRequest(BaseModel):
    """What staff may change about a lead — which is all of it.

    A submitted enquiry is evidence, so every change here is recorded against
    the lead with its old value. See `UpdateEnquiry` for why that condition is
    not optional.

    An empty string clears `phone` and `whatsapp`; the fields that must have a
    value refuse it.
    """

    status: EnquiryStatus | None = None
    assigned_to: UUID | None = None
    budget_min_minor: int | None = Field(default=None, ge=0)
    budget_max_minor: int | None = Field(default=None, ge=0)

    first_name: str | None = Field(default=None, max_length=120)
    last_name: str | None = Field(default=None, max_length=120)
    #: No `email`. It is the lead's identity — the address every message has
    #: already been sent to, and the one conversion matches an account on.
    #: Changing it here would silently point the record at somebody else.
    phone: str | None = Field(default=None, max_length=50)
    whatsapp: str | None = Field(default=None, max_length=50)
    event_type: str | None = Field(default=None, max_length=100)
    message: str | None = Field(default=None, max_length=5000)
    event_date: datetime | None = None
    #: When the work is due. Carries to the project on conversion.
    deadline: datetime | None = None

    @model_validator(mode="after")
    def _reject_an_empty_patch(self) -> "EnquiryUpdateRequest":
        if not self.model_fields_set:
            raise ValueError("Provide at least one field to change.")
        return self


class NoteRequest(BaseModel):
    body: str = Field(min_length=1, max_length=5000)


class ConsultationRequest(BaseModel):
    scheduled_at: datetime
    duration_minutes: int = Field(default=30, ge=5, le=480)
    #: Pasted by the admin while the scheduler is manual. Once a Google Meet
    #: backend exists this becomes optional in a different sense — generated
    #: rather than supplied.
    meeting_url: str | None = Field(default=None, max_length=500)


class ConvertRequest(BaseModel):
    """The name is confirmed, not guessed.

    Still explicit rather than taken from the enquiry: since 2026-09-30 the
    form collects the two parts separately, so the console can prefill this
    with what the person actually typed instead of a split — but the admin
    still confirms, because this becomes the name on their account.
    """

    first_name: str = Field(min_length=1, max_length=120)
    last_name: str = Field(min_length=1, max_length=120)
    title: str = Field(min_length=1, max_length=255)
    event_type: str | None = Field(default=None, max_length=100)
    #: Confirmed here rather than assumed from the lead. Optional on the wire
    #: because a general enquiry may genuinely have no date; the console asks
    #: for them, which is where the judgement belongs.
    event_date: datetime | None = None
    deadline: datetime | None = None


class ConsultationResponse(BaseModel):
    id: UUID
    scheduled_at: datetime
    duration_minutes: int
    #: `requested` means the client picked this from the website and is waiting
    #: to hear. Nothing is in a diary and there is no meeting link until it is
    #: confirmed.
    status: ConsultationStatus
    meeting_url: str | None
    provider: MeetingProvider
    cancelled_at: datetime | None


class EnquiryEventResponse(BaseModel):
    id: UUID
    kind: EnquiryEventKind
    actor_id: UUID | None
    payload: dict
    occurred_at: datetime


class AdminEnquiryResponse(BaseModel):
    id: UUID
    first_name: str
    last_name: str
    #: Derived on the entity — sent so a list does not join two fields in every
    #: row and space them differently each time.
    full_name: str
    email: str
    phone: str | None
    whatsapp: str | None
    event_type: str
    event_date: datetime | None
    deadline: datetime | None
    message: str
    status: EnquiryStatus
    #: Only the legal moves, from the same map the use case enforces.
    allowed_next_statuses: list[EnquiryStatus]
    assigned_to: UUID | None
    assigned_to_name: str | None
    customer_id: UUID | None
    converted_project_id: UUID | None
    budget_min_minor: int | None
    budget_max_minor: int | None
    created_at: datetime


class TriagedEnquiryResponse(BaseModel):
    """One row of the dashboard's triage table.

    A trimmed shape, not `AdminEnquiryResponse`: a glance table needs who, what,
    when and how urgent. Sending the whole lead — message body, budget range,
    phone and WhatsApp — would put every client's contact details into a payload
    that loads on the dashboard of every member of staff, every time.
    """

    id: UUID
    full_name: str
    event_type: str
    #: The date the client chose. Null on anything submitted before the public
    #: form started asking, and on leads an admin has not filled in.
    event_date: datetime | None
    status: EnquiryStatus
    #: How soon the event is, decided server-side so the console and any future
    #: client cannot disagree about what "this week" means.
    band: UrgencyBand
    #: Days until the event; negative once it has passed, null when undated.
    days_until: int | None
    #: How long it has been waiting for a reply. Always known — which is why the
    #: table leans on it for the rows that have no event date.
    days_waiting: int
    assigned_to_name: str | None
    #: Still untouched with the event close. The one flag the table sorts your
    #: attention by.
    needs_chasing: bool
    created_at: datetime


class EnquiryTriageResponse(BaseModel):
    items: list[TriagedEnquiryResponse]
    #: Every open lead, so a table showing the first fifty can say what it is
    #: not showing rather than implying there is nothing more.
    open_total: int


class ExistingAccountResponse(BaseModel):
    """An account already registered to this lead's email address."""

    id: UUID
    first_name: str
    last_name: str
    role: str
    #: False when the address belongs to staff. The project can still be
    #: created, but it will have no client attached and the admin must act.
    is_customer: bool


class AdminEnquiryDetailResponse(AdminEnquiryResponse):
    events: list[EnquiryEventResponse]
    consultations: list[ConsultationResponse]
    #: None when converting will create a new account and issue an invite.
    existing_account: ExistingAccountResponse | None = None


class ConfirmConsultationRequest(BaseModel):
    """Agree the call, or agree it at a different time.

    One request rather than confirm-then-reschedule: an admin looking at a
    requested Thursday they cannot make says "Friday instead", and splitting
    that into two operations invites the one where the time moves and nobody
    is told.
    """

    #: Omitted to accept the time the client asked for.
    scheduled_at: datetime | None = None
    duration_minutes: int | None = Field(default=None, ge=15, le=240)
    meeting_url: str | None = Field(default=None, max_length=500)


class ConversionResponse(BaseModel):
    project_id: UUID
    #: None when the address belonged to a non-customer account; the project
    #: exists but needs a client assigning.
    customer_id: UUID | None
    #: Only when an account was created here, and only outside production.
    invite_url: str | None = None
    #: Something to act on. The conversion succeeded regardless.
    warning: str | None = None


class BookedSlotResponse(BaseModel):
    """One occupied slot on the availability grid.

    Carries the client's name so a busy Tuesday says who each call is with, and
    `ends_at` server-side so the grid never recomputes it from a duration and
    disagrees with the clash rule.
    """

    consultation_id: UUID
    enquiry_id: UUID
    client_name: str
    event_type: str
    starts_at: datetime
    ends_at: datetime
    duration_minutes: int
    meeting_url: str | None


class AvailabilityResponse(BaseModel):
    #: Echoed back so a client rendering a grid cannot disagree with the server
    #: about which window it asked for.
    start: datetime
    end: datetime
    booked: list[BookedSlotResponse]
