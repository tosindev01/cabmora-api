from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import UUID, uuid4


class ProjectEventKind(str, Enum):
    CREATED = "created"
    STAGE_CHANGED = "stage_changed"
    SETTINGS_CHANGED = "settings_changed"
    GALLERY_RELEASED = "gallery_released"
    AMENDMENT_REQUESTED = "amendment_requested"
    APPROVED = "approved"
    PAYMENT_RECEIVED = "payment_received"


@dataclass(frozen=True)
class ProjectEvent:
    """Append-only record of everything that happened to a project.

    Three jobs at once: the customer's timeline, the audit trail, and the answer
    to "who approved this, and when" — which matters the first time a delivery
    is disputed.

    Frozen because an event that can be edited is not an audit trail.
    """

    project_id: UUID
    kind: ProjectEventKind
    #: Null means the system acted rather than a person.
    actor_id: UUID | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    id: UUID = field(default_factory=uuid4)
    occurred_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
