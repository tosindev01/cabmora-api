from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from enum import Enum
from uuid import UUID, uuid4

from app.domain.entities.invoice import PaymentMethod
from app.domain.entities.preferences import SUPPORTED_CURRENCIES

#: What a project is priced in when nobody has said otherwise.
DEFAULT_CURRENCY = "GBP"
from app.core.exceptions import ValidationError
from app.domain.entities.user import User, UserRole


class ProjectStage(str, Enum):
    """The machine state of a project.

    The customer-facing timeline is `ProjectEvent`, not this. The two were
    conflated in the designer's fixtures — the admin console listed five stages
    and the customer portal listed five *different* ones including "Contract
    Signed & Deposit", which is an event with money attached rather than a state
    a project can sit in. Stages drive permissions; events tell the story.
    """

    DRAFT = "draft"          # being set up; the customer cannot see it yet
    BOOKED = "booked"        # confirmed, not yet shot
    SHOOTING = "shooting"
    EDITING = "editing"
    IN_REVIEW = "in_review"  # customer previewing and commenting
    DELIVERED = "delivered"  # approved and released
    CLOSED = "closed"


class WatermarkPolicy(str, Enum):
    ALWAYS = "always"
    #: Watermarks come off when the job is paid for, so nobody has to
    #: remember. This was `until_approved` and came off on sign-off, which
    #: handed over the finished files before any money had arrived — the
    #: client approved the work and already had everything they were paying
    #: for.
    UNTIL_PAID = "until_paid"
    NEVER = "never"


class ReleaseMode(str, Enum):
    SELECTIVE = "selective"      # each gallery is released on its own
    ALL_AT_ONCE = "all_at_once"  # releasing one releases the project


#: The pipeline, in order. Everything about movement is derived from it.
STAGE_SEQUENCE: list["ProjectStage"] = [
    ProjectStage.DRAFT,
    ProjectStage.BOOKED,
    ProjectStage.SHOOTING,
    ProjectStage.EDITING,
    ProjectStage.IN_REVIEW,
    ProjectStage.DELIVERED,
    ProjectStage.CLOSED,
]

#: Stages a project reaches by doing the work, not by somebody saying so.
#:
#: These are set automatically — an upload means editing has started, a
#: release means the client is reviewing — and refused when a human tries to
#: claim them without the work behind it. Before this a project with no
#: photographs at all could be walked to Closed, 100%, one click at a time,
#: and the stage became a label rather than a fact.
EARNED_STAGES = frozenset({ProjectStage.IN_REVIEW, ProjectStage.DELIVERED})

#: Stages at which the client has been shown something and may accept it.
#:
#: Wider than "in review" deliberately. Whether the console happens to have
#: been walked to the right stage is our bookkeeping, not theirs: if a client
#: has photographs in front of them and considers the job done, saying so
#: should work. The three stages missing from this set are the ones where
#: nothing has been shared at all.
ACCEPTABLE_FROM = frozenset(
    {
        ProjectStage.EDITING,
        ProjectStage.IN_REVIEW,
        ProjectStage.DELIVERED,
        ProjectStage.CLOSED,
    }
)


def _transitions() -> dict["ProjectStage", set["ProjectStage"]]:
    """Any stage to any other stage.

    This was "one step forward, any distance back", with Client Review and
    Delivered additionally refused unless the work behind them existed. Both
    rules are gone, on Cabmora's instruction: an admin setting up a wedding
    that already happened had to click through four stages that never applied,
    and the console is operated by people who know more about the job than the
    state machine does.

    What has *not* changed is that the stage still moves on its own when the
    work actually happens — uploading media moves a project to Editing,
    releasing a gallery moves it to Client Review, and a client accepting moves
    it to Delivered. Those live in their own use cases and are unaffected by
    anything here. So the stage is still right by default; it is now also
    overridable, which is a different thing from being unguarded.

    The cost, accepted knowingly: somebody can set Delivered on a project with
    nothing delivered, and the client's portal will say so. The guard that
    prevented it is in the history if it is ever wanted back.
    """
    return {stage: {other for other in ProjectStage if other is not stage} for stage in ProjectStage}


#: Which stages may follow which. Derived, so the rule lives in one place
#: rather than in twenty-eight edges somebody has to keep consistent.
ALLOWED_TRANSITIONS: dict[ProjectStage, set[ProjectStage]] = _transitions()


@dataclass
class Project:
    title: str
    event_type: str
    #: Optional so a project can be set up before the client is known — an
    #: enquiry becomes work before it becomes an account.
    customer_id: UUID | None = None
    #: Null means Cabmora's own work rather than a partner's. One table serves
    #: B2C and B2B2C; a second would duplicate every relationship hanging off it.
    creator_id: UUID | None = None
    description: str = ""
    location: str = ""
    event_date: date | None = None
    deadline: date | None = None
    #: What the job costs, agreed with the client. Minor units, like every
    #: other money in the system — floats and currency do not mix, and a
    #: rounding error on somebody's wedding is not a rounding error to them.
    #: Null until it has been agreed, which is not the same as zero.
    price_minor: int | None = None
    #: What `price_minor` is denominated in, and what any invoice raised for
    #: this project inherits.
    #:
    #: It lives here rather than only on the invoice because without it the
    #: agreed price has no unit at all: 150000 could be £1,500 or $1,500, and
    #: nothing recorded which. A quote and its invoice could disagree and no
    #: screen would show the difference. Per project rather than per client —
    #: a studio working abroad bills that job in the local currency and the
    #: rest in sterling.
    currency: str = DEFAULT_CURRENCY
    #: How this client is expected to pay. A note about intent, not a record
    #: of money: that is `Payment`, which says how each sum actually arrived.
    #: Per project rather than per client — a couple may put the deposit on a
    #: card and transfer the balance.
    payment_method: PaymentMethod | None = None
    stage: ProjectStage = ProjectStage.DRAFT

    # --- Per-project settings, set by the admin in charge ---
    watermark_policy: WatermarkPolicy = WatermarkPolicy.UNTIL_PAID
    release_mode: ReleaseMode = ReleaseMode.SELECTIVE
    #: Whether the client may hand out a public link to this gallery. Off by
    #: default: a link that needs no account is a decision about somebody
    #: else's photographs — the people in them did not agree to anything —
    #: and it should be made deliberately rather than inherited.
    allow_client_sharing: bool = False
    #: Whether the client may save a copy of what they are shown. Off by
    #: default, because the PRD asks for "non-downloadable" galleries and a
    #: default that quietly hands out files is the wrong way round.
    #:
    #: A separate axis from the watermark, not a bypass of it: this decides
    #: whether a save button exists at all, while `hands_over_originals`
    #: decides *which* file is behind it. Downloads on + unpaid + UNTIL_PAID
    #: means they can save the watermarked copy, which is the intended
    #: combination rather than a hole.
    allow_downloads: bool = False
    #: Approval and payment are separate gates on purpose. Some work releases on
    #: sign-off with payment on terms; hard-coding one order into the stage
    #: machine would make the other impossible to sell.
    require_approval_before_delivery: bool = True
    require_payment_before_delivery: bool = False

    #: Who signed the work off, and when. Stored rather than read off the
    #: stage, because DELIVERED -> EDITING -> IN_REVIEW -> DELIVERED is a legal
    #: cycle: the stage alone cannot answer "has this been approved?", and
    #: `WatermarkPolicy.UNTIL_APPROVED` needs a definite answer.
    approved_at: datetime | None = None
    approved_by: UUID | None = None

    #: Cabmora people put on this shoot — a second shooter, an editor, the
    #: coordinator running it. Hydrated by the repository from its own table
    #: because a wedding has several, where `creator_id` holds exactly one.
    #: Empty for projects nobody has been assigned to, which is the default.
    member_ids: list[UUID] = field(default_factory=list)

    id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def is_visible_to_customer(self) -> bool:
        """Every stage, including draft.

        This used to hide `DRAFT`, on the reasoning that a project being set up
        is not one being shown. In practice it produced a project the client
        had already agreed to and could not see, and a "move the stage" step
        somebody had to remember before they could — which is why enquiry
        conversion had already opted out by starting at `BOOKED`.

        Kept as a property rather than deleted, so the question still has one
        home. If a rule ever comes back it belongs in the repository query,
        not in a filter applied to a page after it has been fetched: that is
        what the list did, and it left `total` counting rows the client was
        not shown and pages shorter than the page size.
        """
        return True

    @property
    def is_approved(self) -> bool:
        return self.approved_at is not None

    def approve(self, customer_id: UUID) -> None:
        """The client accepts the work.

        Lives on the entity rather than in the use case because it is two
        facts that must change together — the sign-off and the stage — and
        somewhere that set them apart would eventually set only one.

        **Idempotent.** Accepting twice is not an error, it is somebody
        pressing a button again; the first sign-off stands, because when they
        accepted is the fact a dispute turns on and the second press is not
        new information. This used to raise, and the refusal reached the
        client as a failure for something they had already done successfully.

        An outstanding change request does not block it on purpose: a client
        saying "good enough, send it" should not be held up by something they
        asked for last week. The request stays open for the team.
        """
        if self.is_approved:
            return
        if self.stage not in ACCEPTABLE_FROM:
            raise ValidationError(
                "There is nothing to accept yet — no photographs have been shared."
            )
        self.approved_at = datetime.now(timezone.utc)
        self.approved_by = customer_id
        # Only forwards. A closed project that gets a late sign-off records
        # the sign-off; it does not reopen.
        if self.stage in (ProjectStage.EDITING, ProjectStage.IN_REVIEW):
            self.stage = ProjectStage.DELIVERED

    def withdraw_approval(self) -> None:
        """Re-editing the work retracts the sign-off that covered it.

        Closing does not: closed work was genuinely approved, and the record
        of who approved it is the thing a dispute turns on.
        """
        self.approved_at = None
        self.approved_by = None

    def hands_over_originals(self, *, settled: bool) -> bool:
        """Whether the unwatermarked file may now be handed over.

        A method taking the money rather than a property reading the project,
        because a project knows nothing about invoices and should not: the
        caller asks billing and brings the answer. The *rule* stays here, so
        there is one place that decides what being paid means for a
        watermark.

        `settled` is false for a project nobody has invoiced, which is the
        safe default — originals cannot be handed over by forgetting to bill.
        `NEVER` remains the deliberate override for a cash job or a
        complimentary shoot.
        """
        if self.watermark_policy is WatermarkPolicy.NEVER:
            return True
        if self.watermark_policy is WatermarkPolicy.ALWAYS:
            return False
        return settled

    def __post_init__(self) -> None:
        # `None` means the same as not passing it at all. The API's optional
        # `currency` field arrives as None whenever a caller omits it, and
        # every one of those is "bill it the usual way" rather than an error.
        if not self.currency:
            self.currency = DEFAULT_CURRENCY
        self.currency = self.currency.upper()
        if self.currency not in SUPPORTED_CURRENCIES:
            raise ValidationError(
                f"{self.currency} is not a currency we can bill in."
            )

    @property
    def progress(self) -> int:
        """Derived from the stage, never stored.

        A stored percentage drifts the first time someone moves the stage and
        not the number — which is precisely what the current fixtures do.
        """
        order = list(ProjectStage)
        return round(order.index(self.stage) / (len(order) - 1) * 100)

    def release_targets(
        self, on_project: list[UUID], chosen: list[UUID]
    ) -> list[UUID]:
        """Which photographs a release gesture actually touches.

        Under `ALL_AT_ONCE` the selection is only a trigger: releasing
        anything releases the set, because that is what the setting promises
        the client. Under `SELECTIVE` it is exactly what was picked.

        Lives on the entity because two callers need the same answer —
        `ReleaseAssets`, which does it, and `PreviewRelease`, which tells an
        admin what is about to happen before they confirm. A second copy of
        this rule in the console is how a dialog ends up confidently
        describing a release that does something else.
        """
        if self.release_mode is ReleaseMode.ALL_AT_ONCE:
            return list(on_project)
        return list(chosen)

    @property
    def stage_after_release(self) -> "ProjectStage | None":
        """Where releasing photographs puts this project, or None to stay put.

        Photographs with the client means the client is reviewing them, so
        this is set rather than left to an admin — a stage nobody trusts is
        one nobody reads. Only from Editing: a delivered project that has a
        frame re-released has not gone back into review, that is an amendment.

        A property for the same reason as `release_targets`: `ReleaseAssets`
        does it and `PreviewRelease` warns about it, and the two must not be
        able to disagree about where a project is going.
        """
        return (
            ProjectStage.IN_REVIEW if self.stage is ProjectStage.EDITING else None
        )

    def can_move_to(self, stage: ProjectStage) -> bool:
        return stage in ALLOWED_TRANSITIONS[self.stage]

    @property
    def allowed_next_stages(self) -> list["ProjectStage"]:
        """What this project may move to, in declared order.

        Every stage but the one it is already in. Still derived from the same
        map `can_move_to` enforces rather than listed separately — the console
        builds its dropdown from this, and two copies of "what is allowed"
        would be two rules that must agree.
        """
        allowed = ALLOWED_TRANSITIONS[self.stage]
        return [stage for stage in ProjectStage if stage in allowed]

    def is_managed_by(self, user: User) -> bool:
        """Who may edit, upload to, and move this project.

        Defined once, on the entity, because uploads, stage changes, settings
        and gallery release all need the same answer — and re-deriving it per
        endpoint is how a creator ends up editing someone else's project.
        """
        if user.role is UserRole.ADMIN:
            return True
        # A customer is never a manager of their own project, whatever else
        # is true of them. Stated before membership rather than after,
        # because an id landing in `member_ids` by mistake must not be able
        # to promote the person it belongs to.
        if user.role is UserRole.CUSTOMER:
            return False
        return user.id == self.creator_id or user.id in self.member_ids

    def is_visible_to(self, user: User) -> bool:
        """Managers always; the customer whenever it is theirs.

        An unassigned project has no customer, so it is visible to managers
        only — which falls out of the same check rather than needing its own.
        """
        return self.is_managed_by(user) or (
            self.customer_id is not None
            and self.customer_id == user.id
            and self.is_visible_to_customer
        )
