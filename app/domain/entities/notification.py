"""Something that happened, addressed to one person.

A row per recipient rather than a row per event with a join table of readers.
An event has an audience, and the audience is resolved once when it happens —
"every admin" means the admins who were there, not whoever holds the role when
the bell is next opened. Resolving it at read time would quietly show a new
coordinator six months of history on their first morning, and would lose the
read state the moment somebody's role changed.

This is deliberately **not** a copy of the email that went out. Email is a
different channel with a different contract: it can be declined, it arrives
once, and it has to carry enough context to be read away from the product. A
notification is a pointer — one line of what happened and where to go. The two
are produced from the same events, and neither is derived from the other.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from uuid import UUID, uuid4

from app.core.exceptions import ValidationError

#: One line in a dropdown. Longer than this is a body, not a title.
MAX_TITLE = 160
#: The substance — a quoted message, an amount, a photo count. Long enough to
#: answer "does this need me?" without opening it, short enough that a feed of
#: twenty does not become a page of prose.
MAX_BODY = 400


class NotificationTopic(str, Enum):
    """What the notice is about.

    Grouped by the thing that happened rather than by who is told, because the
    same topic goes to both sides — a message is a message whether the client
    or the studio wrote it, and a feed filtered by "messages" should show the
    conversation, not half of it.

    These are the categories Cabmora named, plus the two the product already
    emits and would otherwise have had nowhere to sit (`creator`, `support`).
    """

    #: A lead arrived from the public form.
    ENQUIRY = "enquiry"
    #: A consultation was put in the diary, moved or is about to start.
    BOOKING = "booking"
    #: Somebody wrote something — a comment, an amendment, a reply.
    MESSAGE = "message"
    #: An invoice was issued, or money arrived.
    INVOICE = "invoice"
    #: Photographs were released, or a gallery changed.
    GALLERY = "gallery"
    #: The job moved — a stage change, an approval.
    PROJECT = "project"
    #: A studio applied to join Flow, or was let in.
    CREATOR = "creator"
    #: Somebody reported something broken.
    SUPPORT = "support"


@dataclass
class Notification:
    user_id: UUID
    topic: NotificationTopic
    #: What happened, in a sentence somebody can act on: "Amara Okafor replied
    #: on Okonkwo Wedding", not "New message".
    title: str
    #: The substance. Empty where there is none to add — a stage change says
    #: everything in its title.
    body: str = ""
    #: Where to go, as a **path** on whichever app the recipient uses:
    #: `/projects/<id>`, `/enquiries`. Not an absolute URL — the API does not
    #: know which origin served this person, and an origin baked in here is how
    #: a coordinator's bell starts sending them to the customer portal.
    #:
    #: Null for a notice with nowhere useful to go.
    url: str | None = None
    #: Null until opened. A timestamp rather than a boolean so "3 unread" and
    #: "read an hour ago" are the same column, and so a future "catch me up
    #: since Friday" has something to filter on.
    read_at: datetime | None = None
    id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        self.title = self.title.strip()
        self.body = self.body.strip()
        if not self.title:
            raise ValidationError("A notification needs to say what happened.")
        if len(self.title) > MAX_TITLE:
            raise ValidationError(f"A notification title is at most {MAX_TITLE} characters.")
        if len(self.body) > MAX_BODY:
            # Truncated rather than refused: the body is somebody else's prose
            # arriving through a quoted message, and a client writing a long
            # paragraph must not be the reason a notice fails to be recorded.
            self.body = self.body[: MAX_BODY - 1].rstrip() + "…"
        if self.url is not None and (
            not self.url.startswith("/") or self.url.startswith("//")
        ):
            # `//host` is rejected as well as `https://host`. It looks like a
            # path and passes a `startswith("/")` check, but a browser reads it
            # as protocol-relative and leaves the site — so a notice whose link
            # came from anything but our own code could walk somebody off to
            # another origin from inside their own portal.
            raise ValidationError("A notification link has to be a path on this site.")

    @property
    def is_read(self) -> bool:
        return self.read_at is not None

    def mark_read(self) -> None:
        """Idempotent: re-reading must not move the stamp forward, or "read an
        hour ago" becomes "read just now" every time the dropdown opens."""
        if self.read_at is None:
            self.read_at = datetime.now(timezone.utc)
