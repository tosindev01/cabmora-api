from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from app.domain.entities.invoice import PaymentMethod
from app.domain.entities.project import ProjectStage, ReleaseMode, WatermarkPolicy
from app.domain.entities.project_event import ProjectEventKind


class ProjectCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    event_type: str = Field(min_length=1, max_length=100)
    #: Optional: a project can be set up before the client has an account. The
    #: admin either picks an existing customer, provisions one via
    #: POST /admin/users, or leaves this empty and assigns later.
    customer_id: UUID | None = None
    creator_id: UUID | None = None
    description: str = Field(default="", max_length=5000)
    location: str = Field(default="", max_length=255)
    event_date: date | None = None
    deadline: date | None = None
    #: What this job is priced and billed in. Validated against the same
    #: list the entity uses, so a typo is refused here rather than
    #: reaching somebody's invoice.
    currency: str | None = Field(default=None, min_length=3, max_length=3)


class ProjectUpdateRequest(BaseModel):
    """Details and settings. `stage` is absent on purpose — it moves through
    POST /stage so the transition rules cannot be bypassed by a PATCH."""

    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=5000)
    event_type: str | None = Field(default=None, min_length=1, max_length=100)
    location: str | None = Field(default=None, max_length=255)
    event_date: date | None = None
    deadline: date | None = None
    creator_id: UUID | None = None
    #: Assignable once, while the project has no customer. See UpdateProject.
    customer_id: UUID | None = None
    #: Minor units. Entered when the job is agreed and changed when it
    #: changes — a quote is not a contract.
    price_minor: int | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    payment_method: PaymentMethod | None = None

    watermark_policy: WatermarkPolicy | None = None
    release_mode: ReleaseMode | None = None
    require_approval_before_delivery: bool | None = None
    require_payment_before_delivery: bool | None = None
    #: Whether the client may hand out a public link to this gallery.
    allow_client_sharing: bool | None = None
    allow_downloads: bool | None = None

    @model_validator(mode="after")
    def _reject_an_empty_patch(self) -> "ProjectUpdateRequest":
        if not self.model_fields_set:
            raise ValueError("Provide at least one field to change.")
        return self


class ProjectStageRequest(BaseModel):
    stage: ProjectStage


class ProjectEventResponse(BaseModel):
    id: UUID
    kind: ProjectEventKind
    actor_id: UUID | None
    payload: dict
    occurred_at: datetime


class ProjectSummaryResponse(BaseModel):
    """What a card needs to be acted on without opening the project."""

    photos: int
    released: int
    #: Client remarks nobody has dealt with — the "you are holding this up"
    #: number.
    open_comments: int
    billed_minor: int
    paid_minor: int
    outstanding_minor: int


class ProjectResponse(BaseModel):
    id: UUID
    title: str
    description: str
    event_type: str
    location: str
    event_date: date | None
    deadline: date | None
    customer_id: UUID | None
    #: Denormalised for display, never stored — resolved per page in one batch
    #: lookup so a list of 30 projects is two queries, not thirty-one.
    customer_name: str | None
    creator_id: UUID | None
    creator_name: str | None
    stage: ProjectStage
    #: Which stages this project may move to. Published so a dropdown offers
    #: only legal moves instead of earning a 422.
    allowed_next_stages: list[ProjectStage]
    #: Derived from `stage` server-side so both frontends cannot disagree
    #: about what "60%" means.
    #: What the job costs, agreed with the client. Minor units; null until
    #: it has been agreed, which is not the same as zero.
    price_minor: int | None = None
    #: What the price and any invoice are denominated in.
    currency: str
    #: How this client is expected to pay. Intent, not a record of money.
    payment_method: PaymentMethod | None = None
    progress: int
    #: Counts and totals from media, feedback and billing. Null only on the
    #: endpoints that answer about one project, where the detail screens ask
    #: those questions directly.
    summary: ProjectSummaryResponse | None = None

    watermark_policy: WatermarkPolicy
    release_mode: ReleaseMode
    require_approval_before_delivery: bool
    require_payment_before_delivery: bool
    #: Whether the client may hand out a link that needs no account. Off
    #: unless an admin turned it on.
    allow_client_sharing: bool
    #: Whether the client may save a copy of what they are shown. Off unless
    #: an admin turned it on. Which file they get is still the watermark
    #: policy's decision, not this one's.
    allow_downloads: bool
    #: Cabmora people put on this shoot. Ids only — the console already
    #: holds the names, and repeating them per project would make a page of
    #: thirty projects carry the same handful of people thirty times.
    member_ids: list[UUID]
    #: Null until the client signs the work off. `approved_by` is deliberately
    #: not published — the timeline already records who, and the id adds
    #: nothing a screen can use.
    approved_at: datetime | None

    created_at: datetime


class ProjectDetailResponse(ProjectResponse):
    """A project with its timeline — one request rather than two, because no
    screen shows one without the other."""

    events: list[ProjectEventResponse]
    #: How to reach the client, resolved from their account. On the detail
    #: response only: a list of thirty projects does not need thirty phone
    #: numbers, and sending them anyway puts client contact details in every
    #: payload any member of staff loads.
    customer_email: str | None = None
    customer_phone: str | None = None
    customer_whatsapp: str | None = None


class RatingRequest(BaseModel):
    stars: int = Field(ge=1, le=5)
    words: str = Field(default="", max_length=2000)
    #: Whether we may quote this publicly. Defaults to no — a rating left in
    #: a private portal is not an offer to appear on a website.
    may_publish: bool = False


class RatingResponse(BaseModel):
    stars: int
    words: str
    may_publish: bool = False
    created_at: datetime
    updated_at: datetime | None
    #: Where to leave the same review publicly, or null when no Google listing
    #: has been configured. A link out: nobody can post a review on somebody
    #: else's behalf, so this opens their form with our listing chosen and the
    #: client writes it themselves.
    google_review_url: str | None = None


class ProjectMembersRequest(BaseModel):
    """Who is on this shoot. Sent as the whole set, not a delta — the console
    edits it as a list, and add/remove endpoints that can disagree are how
    somebody keeps access they were taken off."""

    user_ids: list[UUID] = Field(default_factory=list, max_length=50)
