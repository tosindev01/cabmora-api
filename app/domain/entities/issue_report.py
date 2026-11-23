"""Something a person says is wrong with the platform.

Deliberately not a comment. A comment is about a project and belongs to the
conversation with the studio; this is about the software, has no project, and
is read by whoever maintains it. Folding the two together would put "the
gallery will not load on my phone" in the same thread as feedback on a
photograph.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from uuid import UUID, uuid4

from app.core.exceptions import ValidationError

MAX_SUMMARY = 160
MAX_DETAIL = 4000


class IssueStatus(str, Enum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"


#: What may follow what. Resolved is not an end state — something reported as
#: fixed and still broken has to be able to come back, and a reporter who is
#: told "resolved" when it is not is worse served than one told nothing.
_NEXT: dict[IssueStatus, frozenset[IssueStatus]] = {
    IssueStatus.OPEN: frozenset({IssueStatus.IN_PROGRESS, IssueStatus.RESOLVED}),
    IssueStatus.IN_PROGRESS: frozenset({IssueStatus.OPEN, IssueStatus.RESOLVED}),
    IssueStatus.RESOLVED: frozenset({IssueStatus.OPEN, IssueStatus.IN_PROGRESS}),
}


@dataclass
class IssueReport:
    #: Who reported it. Never null: anonymous reports cannot be replied to, and
    #: a report nobody can be asked about is a guess.
    reporter_id: UUID
    summary: str
    detail: str
    #: The path they were on, captured by the page rather than typed. The
    #: single most useful field and the one nobody fills in by hand.
    page_path: str | None = None
    status: IssueStatus = IssueStatus.OPEN
    #: Set when somebody closes it, with who and what they said.
    resolved_at: datetime | None = None
    resolved_by: UUID | None = None
    resolution: str | None = None
    id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        self.summary = self.summary.strip()
        self.detail = self.detail.strip()
        if not self.summary:
            raise ValidationError("Tell us in a line what went wrong.")
        if len(self.summary) > MAX_SUMMARY:
            raise ValidationError(f"Keep the summary under {MAX_SUMMARY} characters.")
        if not self.detail:
            raise ValidationError("Tell us what happened, so we can look into it.")
        if len(self.detail) > MAX_DETAIL:
            raise ValidationError(f"Keep the detail under {MAX_DETAIL} characters.")

    @property
    def is_open(self) -> bool:
        return self.status is not IssueStatus.RESOLVED

    def move_to(
        self, status: IssueStatus, *, by: UUID, resolution: str | None = None
    ) -> None:
        if status is self.status:
            # Idempotent rather than an error: two people clicking "Resolve" on
            # the same row is not a mistake worth a red banner.
            return
        if status not in _NEXT[self.status]:
            raise ValidationError(
                f"An issue cannot go from {self.status.value} to {status.value}."
            )

        self.status = status
        if status is IssueStatus.RESOLVED:
            self.resolved_at = datetime.now(timezone.utc)
            self.resolved_by = by
            self.resolution = (resolution or "").strip() or None
        else:
            # Reopened. The old closing note would describe a fix that evidently
            # did not hold, so it goes with the resolution it belonged to.
            self.resolved_at = None
            self.resolved_by = None
            self.resolution = None
