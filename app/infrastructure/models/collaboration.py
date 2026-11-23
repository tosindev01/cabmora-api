from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.entities.collaboration import (
    CallStatus,
    ProjectCall,
    ProjectTask,
    TaskPriority,
    TaskStatus,
)
from app.infrastructure.database import Base


class ProjectTaskModel(Base):
    __tablename__ = "project_tasks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(36), index=True)
    title: Mapped[str] = mapped_column(String(240))
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default=TaskStatus.TODO.value, index=True)
    priority: Mapped[str] = mapped_column(String(20), default=TaskPriority.MEDIUM.value)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    assignee_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    created_by: Mapped[str] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    def to_entity(self) -> ProjectTask:
        return ProjectTask(
            id=UUID(self.id),
            project_id=UUID(self.project_id),
            title=self.title,
            description=self.description,
            status=TaskStatus(self.status),
            priority=TaskPriority(self.priority),
            due_at=self.due_at,
            assignee_id=UUID(self.assignee_id) if self.assignee_id else None,
            created_by=UUID(self.created_by),
            created_at=self.created_at,
        )

    @classmethod
    def from_entity(cls, t: ProjectTask) -> "ProjectTaskModel":
        return cls(
            id=str(t.id),
            project_id=str(t.project_id),
            title=t.title,
            description=t.description,
            status=t.status.value,
            priority=t.priority.value,
            due_at=t.due_at,
            assignee_id=str(t.assignee_id) if t.assignee_id else None,
            created_by=str(t.created_by),
            created_at=t.created_at,
        )


class ProjectCallModel(Base):
    __tablename__ = "project_calls"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(36), index=True)
    requester_id: Mapped[str] = mapped_column(String(36), index=True)
    recipient_id: Mapped[str] = mapped_column(String(36), index=True)
    title: Mapped[str] = mapped_column(String(200))
    notes: Mapped[str] = mapped_column(Text, default="")
    proposed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    duration_minutes: Mapped[int] = mapped_column(Integer, default=30)
    status: Mapped[str] = mapped_column(
        String(20), default=CallStatus.PENDING.value, index=True
    )
    meeting_room_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    meeting_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    responded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    reminder_sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    def to_entity(self) -> ProjectCall:
        return ProjectCall(
            id=UUID(self.id),
            project_id=UUID(self.project_id),
            requester_id=UUID(self.requester_id),
            recipient_id=UUID(self.recipient_id),
            title=self.title,
            notes=self.notes,
            proposed_at=self.proposed_at,
            duration_minutes=self.duration_minutes,
            status=CallStatus(self.status),
            meeting_room_id=self.meeting_room_id,
            meeting_url=self.meeting_url,
            responded_at=self.responded_at,
            reminder_sent_at=self.reminder_sent_at,
            created_at=self.created_at,
        )

    @classmethod
    def from_entity(cls, c: ProjectCall) -> "ProjectCallModel":
        return cls(
            id=str(c.id),
            project_id=str(c.project_id),
            requester_id=str(c.requester_id),
            recipient_id=str(c.recipient_id),
            title=c.title,
            notes=c.notes,
            proposed_at=c.proposed_at,
            duration_minutes=c.duration_minutes,
            status=c.status.value,
            meeting_room_id=c.meeting_room_id,
            meeting_url=c.meeting_url,
            responded_at=c.responded_at,
            reminder_sent_at=c.reminder_sent_at,
            created_at=c.created_at,
        )
