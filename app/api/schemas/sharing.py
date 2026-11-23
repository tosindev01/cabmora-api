from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class ShareCreateRequest(BaseModel):
    #: What the client calls it — "Mum", "the group chat". Optional, and what
    #: makes a list of three links something a person can act on.
    label: str = Field(default="", max_length=80)
    #: The photographs to show, by the id the gallery lists.
    #:
    #: Omitted or null shares the whole gallery, which is what sharing did
    #: before there was a choice — so an older client keeps working. A list
    #: shares those and nothing else. An empty list is refused rather than
    #: guessed at: "none" and "all" differ by the entire gallery, and the
    #: wrong guess is somebody sending their whole wedding to a group chat
    #: while believing they sent one photograph.
    asset_ids: list[UUID] | None = Field(default=None, max_length=500)


class ShareResponse(BaseModel):
    """A link as its owner sees it. The secret is absent on purpose — it is
    returned once, by the call that creates it, and is unrecoverable after."""

    id: UUID
    label: str
    created_at: datetime
    expires_at: datetime
    revoked_at: datetime | None
    last_viewed_at: datetime | None
    views: int
    #: Live right now. Published rather than left to the browser to work out
    #: from two timestamps and the current clock.
    active: bool
    #: How many photographs are behind the link, or null when it is the whole
    #: gallery. Null and 0 are different answers: one is "everything", the
    #: other is a selective link whose photographs have since been deleted.
    #: A list of links has to be able to say which it is holding.
    photograph_count: int | None = None


class IssuedShareResponse(ShareResponse):
    #: The whole link, including the secret. Shown once; if it is lost the
    #: answer is to make another and revoke this one.
    url: str


class SharedPhotographResponse(BaseModel):
    id: str
    filename: str
    url: str
    #: So the page draws a player for a film and an image for a photograph.
    content_type: str | None = None


class SharedGalleryResponse(BaseModel):
    """What somebody holding a link gets. No ids that lead anywhere, no
    client details, no stage, no money — a link is to the photographs."""

    project_title: str
    event_type: str
    photographs: list[SharedPhotographResponse]
    expires_at: datetime
    #: Whether these are the finished files or marked proofs, so the page can
    #: say which rather than leave somebody wondering about the watermark.
    hands_over_originals: bool
