from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.domain.entities.rating import ReviewStatus


class ReviewResponse(BaseModel):
    """A review as the moderation queue shows it."""

    id: UUID
    project_id: UUID
    project_title: str | None
    client_name: str | None
    client_email: str | None
    stars: int
    words: str
    #: Whether the client offered these words for publication. An admin can
    #: hide anything, but can only publish what was offered — so this is the
    #: field that decides whether the publish control appears at all.
    may_publish: bool
    status: ReviewStatus
    moderated_at: datetime | None
    created_at: datetime
    updated_at: datetime | None


class PublicReviewResponse(BaseModel):
    """A review as the public site shows it.

    No ids, no project, no email, and the name cut to a first name and an
    initial: they agreed to be quoted, not to be indexed.
    """

    stars: int
    words: str
    name: str | None
    created_at: datetime
