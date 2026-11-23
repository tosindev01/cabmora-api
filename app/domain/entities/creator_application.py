from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from uuid import UUID, uuid4

from app.core.exceptions import ValidationError


class ApplicationStatus(str, Enum):
    """Where an application is. A real state machine, unlike the survey
    answers below — which is why this one is an enum and they are not."""

    PENDING = "pending"
    APPROVED = "approved"
    DECLINED = "declined"


@dataclass
class CreatorApplication:
    """A photographer or studio asking to deliver their work through Flow.

    The studio details are what the application is judged on. The three survey
    answers — volume, storage, bottleneck — are stored as **free text rather
    than enums** on purpose: they are options on a marketing page, chosen to
    qualify a lead, and the day somebody adds "100+ shoots" to the dropdown
    should not be the day this table needs a migration. `status` is an enum
    because it is the one field with rules attached.
    """

    studio_name: str
    applicant_name: str
    email: str
    #: Instagram, a website, a Vimeo channel — whatever they judge themselves
    #: by. Optional: a filmmaker between sites is not a worse applicant.
    portfolio_url: str | None = None
    discipline: str = ""
    annual_volume: str = ""
    storage_needs: str = ""
    bottleneck: str = ""
    #: Which plan they picked on the way in. Not a commitment — nothing is
    #: charged here — but it tells us what they think they need.
    plan: str = ""

    status: ApplicationStatus = ApplicationStatus.PENDING
    #: Why, when declined. Kept even after the fact: "we already spoke to them
    #: and said no" is the thing a second reviewer needs to know.
    decision_note: str | None = None
    reviewed_by: UUID | None = None
    reviewed_at: datetime | None = None
    #: The account created on approval, so the application and the creator it
    #: produced can be read back to each other.
    created_user_id: UUID | None = None

    id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def is_decided(self) -> bool:
        return self.status is not ApplicationStatus.PENDING

    def approve(self, reviewer_id: UUID, user_id: UUID) -> None:
        self._decide(reviewer_id)
        self.status = ApplicationStatus.APPROVED
        self.created_user_id = user_id

    def decline(self, reviewer_id: UUID, note: str | None = None) -> None:
        self._decide(reviewer_id)
        self.status = ApplicationStatus.DECLINED
        self.decision_note = note

    def _decide(self, reviewer_id: UUID) -> None:
        """Decided once.

        Refusing a second decision matters more here than it looks: approving
        an already-approved application would create a second account for the
        same studio, and the first one may already have their work in it.
        """
        if self.is_decided:
            raise ValidationError(
                f"This application was already {self.status.value}."
            )
        self.reviewed_by = reviewer_id
        self.reviewed_at = datetime.now(timezone.utc)
