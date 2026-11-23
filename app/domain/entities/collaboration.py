from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from uuid import UUID, uuid4

from app.core.exceptions import ValidationError


class TaskStatus(str, Enum):
    TODO = "todo"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"


class TaskPriority(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass
class ProjectTask:
    project_id: UUID
    title: str
    created_by: UUID
    description: str = ""
    status: TaskStatus = TaskStatus.TODO
    priority: TaskPriority = TaskPriority.MEDIUM
    due_at: datetime | None = None
    assignee_id: UUID | None = None
    id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        self.title = self.title.strip()
        if not self.title:
            raise ValidationError("A task needs a title.")


class CallStatus(str, Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    DECLINED = "declined"
    CANCELLED = "cancelled"
    COMPLETED = "completed"


@dataclass
class ProjectCall:
    project_id: UUID
    requester_id: UUID
    recipient_id: UUID
    title: str
    proposed_at: datetime
    notes: str = ""
    duration_minutes: int = 30
    status: CallStatus = CallStatus.PENDING
    meeting_room_id: str | None = None
    meeting_url: str | None = None
    responded_at: datetime | None = None
    reminder_sent_at: datetime | None = None
    id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def accept(self) -> None:
        if self.status is not CallStatus.PENDING:
            raise ValidationError("Only a pending call request can be accepted.")
        room = f"cabmora-{str(self.id)[:12]}"
        self.status = CallStatus.ACCEPTED
        self.meeting_room_id = room
        self.meeting_url = f"https://meet.jit.si/{room}"
        self.responded_at = datetime.now(timezone.utc)

    def decline(self) -> None:
        if self.status is not CallStatus.PENDING:
            raise ValidationError("Only a pending call request can be declined.")
        self.status = CallStatus.DECLINED
        self.responded_at = datetime.now(timezone.utc)

    def cancel(self) -> None:
        if self.status in (CallStatus.CANCELLED, CallStatus.COMPLETED, CallStatus.DECLINED):
            raise ValidationError("This call can no longer be cancelled.")
        self.status = CallStatus.CANCELLED
        self.responded_at = datetime.now(timezone.utc)

    def complete(self) -> None:
        if self.status is not CallStatus.ACCEPTED:
            raise ValidationError("Only an accepted call can be marked completed.")
        self.status = CallStatus.COMPLETED

    def reschedule(self, new_proposed_at: datetime) -> None:
        if self.status in (CallStatus.CANCELLED, CallStatus.COMPLETED):
            raise ValidationError("This call cannot be rescheduled.")
        self.proposed_at = new_proposed_at
        self.status = CallStatus.PENDING
        self.reminder_sent_at = None
        self.responded_at = None
