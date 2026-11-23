from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.entities.creator_application import (
    ApplicationStatus,
    CreatorApplication,
)
from app.infrastructure.database import Base


class CreatorApplicationModel(Base):
    __tablename__ = "creator_applications"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)

    studio_name: Mapped[str] = mapped_column(String(255))
    applicant_name: Mapped[str] = mapped_column(String(255))
    # Indexed: every submission asks "has this address already applied?".
    email: Mapped[str] = mapped_column(String(320), index=True)
    portfolio_url: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Survey answers, kept as text — see the entity for why these are not enums.
    discipline: Mapped[str] = mapped_column(String(60), default="")
    annual_volume: Mapped[str] = mapped_column(String(60), default="")
    storage_needs: Mapped[str] = mapped_column(String(60), default="")
    bottleneck: Mapped[str] = mapped_column(String(60), default="")
    plan: Mapped[str] = mapped_column(String(60), default="")

    status: Mapped[str] = mapped_column(
        String(20), default=ApplicationStatus.PENDING.value, index=True
    )
    decision_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_user_id: Mapped[str | None] = mapped_column(String(36), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    def to_entity(self) -> CreatorApplication:
        return CreatorApplication(
            id=UUID(self.id),
            studio_name=self.studio_name,
            applicant_name=self.applicant_name,
            email=self.email,
            portfolio_url=self.portfolio_url,
            discipline=self.discipline,
            annual_volume=self.annual_volume,
            storage_needs=self.storage_needs,
            bottleneck=self.bottleneck,
            plan=self.plan,
            status=ApplicationStatus(self.status),
            decision_note=self.decision_note,
            reviewed_by=UUID(self.reviewed_by) if self.reviewed_by else None,
            reviewed_at=self.reviewed_at,
            created_user_id=UUID(self.created_user_id) if self.created_user_id else None,
            created_at=self.created_at,
        )

    @classmethod
    def from_entity(cls, a: CreatorApplication) -> "CreatorApplicationModel":
        return cls(
            id=str(a.id),
            studio_name=a.studio_name,
            applicant_name=a.applicant_name,
            email=a.email,
            portfolio_url=a.portfolio_url,
            discipline=a.discipline,
            annual_volume=a.annual_volume,
            storage_needs=a.storage_needs,
            bottleneck=a.bottleneck,
            plan=a.plan,
            status=a.status.value,
            decision_note=a.decision_note,
            reviewed_by=str(a.reviewed_by) if a.reviewed_by else None,
            reviewed_at=a.reviewed_at,
            created_user_id=str(a.created_user_id) if a.created_user_id else None,
            created_at=a.created_at,
        )
