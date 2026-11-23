from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.domain.entities.comment import MAX_BODY
from app.domain.entities.project import ProjectStage


class CommentCreateRequest(BaseModel):
    body: str = Field(min_length=1, max_length=MAX_BODY)
    #: Omit for feedback about the project rather than one photograph.
    asset_id: UUID | None = None
    #: Set when replying to an existing comment thread.
    parent_id: UUID | None = None
    #: Where on the photograph, 0.0–1.0 on each axis. Both or neither.
    #: Omitted for feedback about the picture as a whole.
    point_x: float | None = Field(default=None, ge=0.0, le=1.0)
    point_y: float | None = Field(default=None, ge=0.0, le=1.0)
    #: "amendment" is a request somebody owes an answer to; "comment" is a
    #: remark. Only the first counts towards outstanding work.
    kind: str = "comment"


class CommentResponse(BaseModel):
    id: UUID
    project_id: UUID
    asset_id: UUID | None
    parent_id: UUID | None = None
    point_x: float | None = None
    point_y: float | None = None
    author_id: UUID
    author_name: str
    author_avatar_url: str | None = None
    author_role: str | None = None
    body: str
    kind: str
    resolved: bool
    #: True for an amendment nobody has dealt with — the flag the console
    #: counts, derived rather than stored.
    needs_action: bool
    created_at: datetime


class ConversationResponse(BaseModel):
    """One project's thread, as the client's Messages screen shows it."""

    project_id: UUID
    project_title: str
    event_type: str
    stage: ProjectStage
    messages: list[CommentResponse]
