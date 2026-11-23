from datetime import datetime

from typing import Any

from sqlalchemy import JSON, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.entities.consultation import (
    Consultation,
    ConsultationStatus,
    MeetingProvider,
)
from app.domain.entities.enquiry import Enquiry, EnquiryStatus
from app.domain.entities.enquiry_event import EnquiryEvent, EnquiryEventKind
from app.infrastructure.database import Base


class EnquiryModel(Base):
    __tablename__ = "enquiries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    first_name: Mapped[str] = mapped_column(String(120))
    last_name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(255), index=True)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    whatsapp: Mapped[str | None] = mapped_column(String(50), nullable=True)
    event_type: Mapped[str] = mapped_column(String(100))
    event_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    deadline: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    message: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(
        String(30), default=EnquiryStatus.NEW.value, index=True
    )
    assigned_to: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    customer_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    converted_project_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    budget_min_minor: Mapped[int | None] = mapped_column(Integer, nullable=True)
    budget_max_minor: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    def to_entity(self) -> Enquiry:
        from uuid import UUID

        return Enquiry(
            id=UUID(self.id),
            first_name=self.first_name,
            last_name=self.last_name,
            email=self.email,
            phone=self.phone,
            whatsapp=self.whatsapp,
            event_type=self.event_type,
            event_date=self.event_date,
            deadline=self.deadline,
            message=self.message,
            status=EnquiryStatus(self.status),
            assigned_to=UUID(self.assigned_to) if self.assigned_to else None,
            customer_id=UUID(self.customer_id) if self.customer_id else None,
            converted_project_id=UUID(self.converted_project_id)
            if self.converted_project_id
            else None,
            budget_min_minor=self.budget_min_minor,
            budget_max_minor=self.budget_max_minor,
            created_at=self.created_at,
        )

    @classmethod
    def from_entity(cls, enquiry: Enquiry) -> "EnquiryModel":
        return cls(
            id=str(enquiry.id),
            first_name=enquiry.first_name,
            last_name=enquiry.last_name,
            email=enquiry.email,
            phone=enquiry.phone,
            whatsapp=enquiry.whatsapp,
            event_type=enquiry.event_type,
            event_date=enquiry.event_date,
            deadline=enquiry.deadline,
            message=enquiry.message,
            status=enquiry.status.value,
            assigned_to=str(enquiry.assigned_to) if enquiry.assigned_to else None,
            customer_id=str(enquiry.customer_id) if enquiry.customer_id else None,
            converted_project_id=str(enquiry.converted_project_id)
            if enquiry.converted_project_id
            else None,
            budget_min_minor=enquiry.budget_min_minor,
            budget_max_minor=enquiry.budget_max_minor,
            created_at=enquiry.created_at,
        )


class EnquiryEventModel(Base):
    __tablename__ = "enquiry_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    enquiry_id: Mapped[str] = mapped_column(String(36), index=True)
    kind: Mapped[str] = mapped_column(String(40))
    actor_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    # JSON rather than a column per kind: payloads differ by event, and a wide
    # sparse table would gain a column every time a kind is added.
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    def to_entity(self) -> EnquiryEvent:
        from uuid import UUID

        return EnquiryEvent(
            id=UUID(self.id),
            enquiry_id=UUID(self.enquiry_id),
            kind=EnquiryEventKind(self.kind),
            actor_id=UUID(self.actor_id) if self.actor_id else None,
            payload=self.payload or {},
            occurred_at=self.occurred_at,
        )

    @classmethod
    def from_entity(cls, event: EnquiryEvent) -> "EnquiryEventModel":
        return cls(
            id=str(event.id),
            enquiry_id=str(event.enquiry_id),
            kind=event.kind.value,
            actor_id=str(event.actor_id) if event.actor_id else None,
            payload=event.payload,
            occurred_at=event.occurred_at,
        )


class ConsultationModel(Base):
    __tablename__ = "consultations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    enquiry_id: Mapped[str] = mapped_column(String(36), index=True)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    duration_minutes: Mapped[int] = mapped_column(Integer, default=30)
    status: Mapped[str] = mapped_column(
        String(20), default=ConsultationStatus.CONFIRMED.value, index=True
    )
    meeting_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    provider: Mapped[str] = mapped_column(String(20), default=MeetingProvider.MANUAL.value)
    cancelled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Indexed: the reminder job asks "not yet sent, starting soon" every few
    # minutes, forever.
    reminder_sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    def to_entity(self) -> Consultation:
        from uuid import UUID

        return Consultation(
            id=UUID(self.id),
            enquiry_id=UUID(self.enquiry_id),
            scheduled_at=self.scheduled_at,
            duration_minutes=self.duration_minutes,
            status=ConsultationStatus(self.status),
            meeting_url=self.meeting_url,
            provider=MeetingProvider(self.provider),
            cancelled_at=self.cancelled_at,
            reminder_sent_at=self.reminder_sent_at,
            created_by=UUID(self.created_by) if self.created_by else None,
            created_at=self.created_at,
        )

    @classmethod
    def from_entity(cls, c: Consultation) -> "ConsultationModel":
        return cls(
            id=str(c.id),
            enquiry_id=str(c.enquiry_id),
            scheduled_at=c.scheduled_at,
            duration_minutes=c.duration_minutes,
            status=c.status.value,
            meeting_url=c.meeting_url,
            provider=c.provider.value,
            cancelled_at=c.cancelled_at,
            reminder_sent_at=c.reminder_sent_at,
            created_by=str(c.created_by) if c.created_by else None,
            created_at=c.created_at,
        )
