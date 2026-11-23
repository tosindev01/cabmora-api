from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Boolean, Date, DateTime, Integer, JSON, String, Text
from sqlalchemy import false as sa_false
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.entities.invoice import PaymentMethod
from app.domain.entities.project import (
    Project,
    ProjectStage,
    ReleaseMode,
    WatermarkPolicy,
)
from app.domain.entities.project_event import ProjectEvent, ProjectEventKind
from app.infrastructure.database import Base


class ProjectMemberModel(Base):
    """Who from Cabmora is on a shoot.

    Its own table rather than a column on `projects`: a wedding carries a
    coordinator, a second shooter and an editor, and a list in a column is a
    list you cannot index, join or constrain.
    """

    __tablename__ = "project_members"

    project_id: Mapped[str] = mapped_column(String(36), primary_key=True, index=True)
    user_id: Mapped[str] = mapped_column(String(36), primary_key=True, index=True)
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ProjectModel(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text, default="")
    event_type: Mapped[str] = mapped_column(String(100))
    location: Mapped[str] = mapped_column(String(255), default="")
    event_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    deadline: Mapped[date | None] = mapped_column(Date, nullable=True)
    #: Minor units. Null until agreed, which is not the same as zero.
    price_minor: Mapped[int | None] = mapped_column(Integer, nullable=True)
    #: ISO 4217. `server_default` because SQLite cannot add a NOT NULL
    #: column without one, and every project predates this field.
    currency: Mapped[str] = mapped_column(String(3), default="GBP", server_default="GBP")
    payment_method: Mapped[str | None] = mapped_column(String(20), nullable=True)

    customer_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    # Null = Cabmora's own work. Indexed because a creator's project list is a
    # lookup on this column.
    creator_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)

    stage: Mapped[str] = mapped_column(String(20), default=ProjectStage.DRAFT.value, index=True)

    watermark_policy: Mapped[str] = mapped_column(
        String(20), default=WatermarkPolicy.UNTIL_PAID.value
    )
    release_mode: Mapped[str] = mapped_column(String(20), default=ReleaseMode.SELECTIVE.value)
    require_approval_before_delivery: Mapped[bool] = mapped_column(Boolean, default=True)
    require_payment_before_delivery: Mapped[bool] = mapped_column(Boolean, default=False)
    # Off unless an admin turns it on. A link that needs no account is a
    # decision about somebody else's photographs.
    allow_client_sharing: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=sa_false()
    )

    # Off unless an admin turns it on. `server_default` because SQLite cannot
    # add a NOT NULL column without one, and every existing project predates
    # this setting.
    allow_downloads: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=sa_false()
    )

    # Nullable rather than a boolean: "when" and "by whom" are what a disputed
    # delivery turns on, and a flag throws both away.
    approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    approved_by: Mapped[str | None] = mapped_column(String(36), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    def to_entity(self, member_ids: list[UUID] | None = None) -> Project:
        """`member_ids` is passed in by the repository, which knows how to
        load them in one query for a page rather than one per row."""
        return Project(
            member_ids=member_ids or [],
            id=UUID(self.id),
            title=self.title,
            description=self.description,
            event_type=self.event_type,
            location=self.location,
            event_date=self.event_date,
            deadline=self.deadline,
            price_minor=self.price_minor,
            currency=self.currency or "GBP",
            payment_method=PaymentMethod(self.payment_method)
            if self.payment_method
            else None,
            customer_id=UUID(self.customer_id) if self.customer_id else None,
            creator_id=UUID(self.creator_id) if self.creator_id else None,
            stage=ProjectStage(self.stage),
            watermark_policy=WatermarkPolicy(self.watermark_policy),
            release_mode=ReleaseMode(self.release_mode),
            require_approval_before_delivery=self.require_approval_before_delivery,
            require_payment_before_delivery=self.require_payment_before_delivery,
            allow_client_sharing=self.allow_client_sharing,
            allow_downloads=self.allow_downloads,
            approved_at=self.approved_at,
            approved_by=UUID(self.approved_by) if self.approved_by else None,
            created_at=self.created_at,
        )

    @classmethod
    def from_entity(cls, project: Project) -> "ProjectModel":
        return cls(
            id=str(project.id),
            title=project.title,
            description=project.description,
            event_type=project.event_type,
            location=project.location,
            event_date=project.event_date,
            deadline=project.deadline,
            price_minor=project.price_minor,
            currency=project.currency,
            payment_method=project.payment_method.value if project.payment_method else None,
            customer_id=str(project.customer_id) if project.customer_id else None,
            creator_id=str(project.creator_id) if project.creator_id else None,
            stage=project.stage.value,
            watermark_policy=project.watermark_policy.value,
            release_mode=project.release_mode.value,
            require_approval_before_delivery=project.require_approval_before_delivery,
            require_payment_before_delivery=project.require_payment_before_delivery,
            allow_client_sharing=project.allow_client_sharing,
            allow_downloads=project.allow_downloads,
            approved_at=project.approved_at,
            approved_by=str(project.approved_by) if project.approved_by else None,
            created_at=project.created_at,
            # `progress` is deliberately absent — it is derived from `stage`.
        )


class ProjectEventModel(Base):
    __tablename__ = "project_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(36), index=True)
    kind: Mapped[str] = mapped_column(String(40))
    actor_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    # JSON rather than columns per kind: the payload differs by event, and a
    # wide sparse table would gain a column every time a new kind is added.
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    def to_entity(self) -> ProjectEvent:
        return ProjectEvent(
            id=UUID(self.id),
            project_id=UUID(self.project_id),
            kind=ProjectEventKind(self.kind),
            actor_id=UUID(self.actor_id) if self.actor_id else None,
            payload=self.payload or {},
            occurred_at=self.occurred_at,
        )

    @classmethod
    def from_entity(cls, event: ProjectEvent) -> "ProjectEventModel":
        return cls(
            id=str(event.id),
            project_id=str(event.project_id),
            kind=event.kind.value,
            actor_id=str(event.actor_id) if event.actor_id else None,
            payload=event.payload,
            occurred_at=event.occurred_at,
        )
