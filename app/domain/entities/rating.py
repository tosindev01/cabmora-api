"""What the client thought of the work.

One per project, not one per photograph. "How was your experience" is a
question about the whole job — the shoot, the editing, the people — and
averaging a set of per-image scores would answer a different question badly.

Separate from `Comment` on purpose. A comment is about a photograph and may
need acting on; a rating is a judgement on finished work and needs nothing. The
two share no fields worth sharing, and putting a score column on a comment
would make every remark look like it was waiting for one.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from uuid import UUID, uuid4

from app.core.exceptions import ValidationError

class ReviewStatus(str, Enum):
    """Whether a client's words may be shown outside their own portal.

    About the *words*, never the score. A hidden review still counts towards
    an average — the alternative is a rating out of the reviews we happened to
    like, which is the number we would then put in front of clients.

    There is deliberately no DELETED member. A review removed is somebody's
    words destroyed by the business they are about; HIDDEN says the same thing
    without throwing the record away.
    """

    PENDING = "pending"      # left by the client, nobody has looked yet
    PUBLISHED = "published"  # live on the public site
    HIDDEN = "hidden"        # kept, not shown


MIN_STARS = 1
MAX_STARS = 5
#: Enough for a paragraph somebody means, short enough that the column cannot
#: become a dumping ground.
MAX_WORDS = 2000


@dataclass
class Rating:
    project_id: UUID
    customer_id: UUID
    stars: int
    #: Optional. A score with nothing said is still worth having — most people
    #: will not write anything, and demanding it would cost the score too.
    words: str = ""
    id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    #: Set when a client changes their mind. Kept rather than silently
    #: overwriting `created_at`, because "rated three a week ago, five today"
    #: is a different story from "rated five".
    updated_at: datetime | None = None
    #: Whether the client is happy for this to be quoted publicly. Asked at
    #: the moment they write it, because that is the only moment they are
    #: thinking about what they said. False by default: a rating left inside
    #: a private portal is not an offer to appear on a homepage, and treating
    #: it as one is using somebody's words in advertising without asking.
    may_publish: bool = False
    status: ReviewStatus = ReviewStatus.PENDING
    moderated_by: UUID | None = None
    moderated_at: datetime | None = None

    def __post_init__(self) -> None:
        self._check(self.stars)
        self.words = self.words.strip()[:MAX_WORDS]

    @staticmethod
    def _check(stars: int) -> None:
        if not MIN_STARS <= stars <= MAX_STARS:
            raise ValidationError(f"A rating is between {MIN_STARS} and {MAX_STARS} stars.")

    def revise(self, *, stars: int, words: str) -> None:
        """Change an existing rating.

        Allowed, and deliberately: a client who rates in the first flush and
        then has a bad week over an amendment should be able to say so, and a
        score somebody cannot change is one they will not leave in the first
        place.
        """
        self._check(stars)
        self.stars = stars
        self.words = words.strip()[:MAX_WORDS]
        self.updated_at = datetime.now(timezone.utc)
        # Back to pending. Whatever was approved before was different words,
        # and a published quote that silently changes under an admin who
        # already signed it off is how a website ends up saying something
        # nobody checked.
        self.status = ReviewStatus.PENDING
        self.moderated_by = None
        self.moderated_at = None

    def publish(self, moderator_id: UUID) -> None:
        """Allow this on the public site.

        Refused without the client's permission. Moderation decides what we
        show; it does not decide what we are allowed to show, and an admin
        cannot grant consent on somebody else's behalf.
        """
        if not self.may_publish:
            raise ValidationError(
                "This client did not offer their words for publication."
            )
        if not self.words:
            raise ValidationError("There is nothing to publish — they left no words.")
        self.status = ReviewStatus.PUBLISHED
        self.moderated_by = moderator_id
        self.moderated_at = datetime.now(timezone.utc)

    def hide(self, moderator_id: UUID) -> None:
        """Take it off the public site, or decline to put it there.

        Always allowed, including on a review the client offered: consent to
        be quoted is not an obligation to quote.
        """
        self.status = ReviewStatus.HIDDEN
        self.moderated_by = moderator_id
        self.moderated_at = datetime.now(timezone.utc)

    @property
    def is_public(self) -> bool:
        return self.status is ReviewStatus.PUBLISHED and self.may_publish
