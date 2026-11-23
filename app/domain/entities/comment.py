"""Feedback on the work, and requests to change it.

Two kinds on one entity rather than two entities, because they share
everything that matters — who said it, about what, when, and whether it has
been dealt with. What differs is obligation: a comment is a remark, an
amendment is a request somebody owes an answer to. That difference drives the
project's outstanding count, so it is modelled explicitly rather than inferred
from wording.

`asset_id` is optional on purpose. Most feedback is about one photograph, but
"the whole set feels cold" belongs to the project, and forcing it onto an
arbitrary image would lose that.
"""

from dataclasses import dataclass, field

from app.core.exceptions import ValidationError
from datetime import datetime, timezone
from enum import Enum
from uuid import UUID, uuid4

#: Long enough for a paragraph of real feedback, short enough that the column
#: cannot become a dumping ground for pasted documents.
MAX_BODY = 2000


class CommentKind(str, Enum):
    #: A remark. Nothing is owed in return.
    COMMENT = "comment"
    #: A change the client wants. Someone has to act or decline.
    AMENDMENT = "amendment"


@dataclass
class Comment:
    project_id: UUID
    author_id: UUID
    body: str
    #: None when the feedback is about the project rather than one photograph.
    asset_id: UUID | None = None
    #: Set when this is a reply to an existing comment/pin thread.
    parent_id: UUID | None = None
    #: Where on the photograph, as a fraction of its width and height — 0.0 is
    #: the left or top edge, 1.0 the right or bottom.
    #:
    #: **Fractions, not pixels, and this cannot be changed later.** The same
    #: photograph is drawn at ~600px in the grid, 2048px in the lightbox and
    #: something else again on a phone, and the preview rendition is a
    #: different size from the original it came from. A pixel coordinate would
    #: mean something different in each of those, and nothing records which one
    #: it was measured against. A fraction lands on the same freckle everywhere.
    #:
    #: Null for a remark about the picture as a whole, which stays a legitimate
    #: thing to say — forcing a pin on "love this one" is just friction.
    point_x: float | None = None
    point_y: float | None = None
    kind: CommentKind = CommentKind.COMMENT
    #: Who closed it, and when. Kept rather than a bare boolean so the
    #: timeline can say "Ada resolved this" instead of "this became true".
    resolved_at: datetime | None = None
    resolved_by: UUID | None = None
    id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        # Both or neither: half a coordinate is not a position, and a pin at
        # (0.4, None) would be drawn somewhere arbitrary rather than refused.
        if (self.point_x is None) != (self.point_y is None):
            raise ValidationError("A pin needs both coordinates, or neither.")
        for value in (self.point_x, self.point_y):
            if value is not None and not 0.0 <= value <= 1.0:
                raise ValidationError("A pin has to sit on the photograph.")
        if self.point_x is not None and self.asset_id is None:
            raise ValidationError("A pin has to be on a particular photograph.")

    @property
    def is_pinned(self) -> bool:
        """Whether this points at a spot rather than the whole picture."""
        return self.point_x is not None and self.point_y is not None

    @property
    def is_resolved(self) -> bool:
        return self.resolved_at is not None

    @property
    def needs_action(self) -> bool:
        """An amendment nobody has dealt with.

        Comments never count: marking a compliment as outstanding work would
        make the number meaningless, and it is the number an admin uses to
        decide whether a project can move on.
        """
        return self.kind is CommentKind.AMENDMENT and not self.is_resolved

    def resolve(self, actor_id: UUID) -> None:
        """Idempotent: resolving twice must not rewrite who closed it first."""
        if self.is_resolved:
            return
        self.resolved_at = datetime.now(timezone.utc)
        self.resolved_by = actor_id

    def reopen(self) -> None:
        """Reopen a resolved thread so it can be revisited."""
        self.resolved_at = None
        self.resolved_by = None
