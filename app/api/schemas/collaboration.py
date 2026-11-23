from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.domain.entities.collaboration import CallStatus, TaskPriority, TaskStatus


class TaskCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=240)
    description: str = Field(default="", max_length=2000)
    priority: TaskPriority = TaskPriority.MEDIUM
    due_at: datetime | None = None
    assignee_id: UUID | None = None


class TaskUpdateRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=240)
    description: str | None = Field(default=None, max_length=2000)
    status: TaskStatus | None = None
    priority: TaskPriority | None = None
    due_at: datetime | None = None


class TaskResponse(BaseModel):
    id: UUID
    project_id: UUID
    title: str
    description: str
    status: TaskStatus
    priority: TaskPriority
    due_at: datetime | None
    assignee_id: UUID | None
    created_by: UUID
    created_at: datetime


class CallCreateRequest(BaseModel):
    title: str = Field(default="Project Video Sync", min_length=1, max_length=200)
    proposed_at: datetime
    duration_minutes: int = Field(default=30, ge=10, le=180)
    notes: str = Field(default="", max_length=2000)


class CallRespondRequest(BaseModel):
    action: Literal["accept", "decline", "cancel", "complete", "reschedule"]
    proposed_at: datetime | None = None


class CallResponse(BaseModel):
    id: UUID
    project_id: UUID
    project_title: str
    requester_id: UUID
    requester_name: str
    recipient_id: UUID
    recipient_name: str
    title: str
    notes: str
    proposed_at: datetime
    duration_minutes: int
    status: CallStatus
    meeting_room_id: str | None
    meeting_url: str | None
    responded_at: datetime | None
    created_at: datetime


class BriefingActionItemResponse(BaseModel):
    kind: str
    title: str
    subtitle: str
    project_id: UUID
    project_title: str
    url: str
    priority: str


class CreatorBriefingResponse(BaseModel):
    headline: str
    summary_text: str
    projects_in_progress: int
    pending_tasks_count: int
    revision_requests_count: int
    unread_comments_count: int
    upcoming_deadlines_count: int
    pending_calls_count: int
    action_items: list[BriefingActionItemResponse]


class BriefingChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=1000)


class BriefingChatResponse(BaseModel):
    reply: str
    suggested_links: list[BriefingActionItemResponse] = Field(default_factory=list)
