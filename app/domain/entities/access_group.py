"""A named bundle of permissions, assignable to people.

An additive role in everything but name: it only ever adds to what the base
role gives. "Senior coordinator" or "Billing cover" is a thing an administrator
can reason about and audit; the same four permissions ticked onto nine people
individually is nine things that drift.

Bounded by the same `GRANTABLE` list as a direct grant. Without that an admin
creates a group containing `USERS`, adds a coordinator, and the coordinator
promotes themselves — the group becomes exactly the ladder out that the direct
grant rules were written to prevent.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import UUID, uuid4

from app.core.exceptions import ValidationError
from app.domain.entities.user import GRANTABLE, Permission

MAX_NAME = 60


@dataclass
class AccessGroup:
    name: str
    permissions: set[Permission] = field(default_factory=set)
    #: How many people are in it. Hydrated by the repository for display, not
    #: stored — a counter on the row is a counter that goes wrong. It is what
    #: lets the console say "9 people are in this group" before somebody
    #: changes it, which is the only warning between an edit and nine people
    #: silently gaining a section.
    member_count: int = 0
    id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        self.rename(self.name)
        self.set_permissions(self.permissions)

    def rename(self, name: str) -> None:
        cleaned = name.strip()
        if not cleaned:
            raise ValidationError("A group needs a name.")
        self.name = cleaned[:MAX_NAME]

    def set_permissions(self, permissions: set[Permission]) -> None:
        """Replace what this group gives.

        Refuses anything outside `GRANTABLE` — see the module docstring. The
        check is here rather than only at the endpoint so a second caller
        cannot route around it.
        """
        forbidden = set(permissions) - GRANTABLE
        if forbidden:
            raise ValidationError(
                "These sections cannot be granted: "
                + ", ".join(sorted(p.value for p in forbidden))
            )
        self.permissions = set(permissions)
