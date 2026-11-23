from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.entities.unmatched_funds import UnmatchedFunds
from app.infrastructure.database import Base


class UnmatchedFundsModel(Base):
    __tablename__ = "unmatched_funds"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    #: Unique, because this is what makes recording a redelivered webhook a
    #: no-op rather than a second notice about the same money.
    reference: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    gateway_customer_reference: Mapped[str] = mapped_column(String(64), index=True)
    customer_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True, index=True
    )
    amount_minor: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    handled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    handled_by_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    def to_entity(self) -> UnmatchedFunds:
        return UnmatchedFunds(
            id=UUID(self.id),
            reference=self.reference,
            gateway_customer_reference=self.gateway_customer_reference,
            customer_id=UUID(self.customer_id) if self.customer_id else None,
            amount_minor=self.amount_minor,
            currency=self.currency,
            received_at=self.received_at,
            handled_at=self.handled_at,
            handled_by_id=(
                UUID(self.handled_by_id) if self.handled_by_id else None
            ),
            note=self.note,
        )

    @classmethod
    def from_entity(cls, funds: UnmatchedFunds) -> "UnmatchedFundsModel":
        return cls(
            id=str(funds.id),
            reference=funds.reference,
            gateway_customer_reference=funds.gateway_customer_reference,
            customer_id=str(funds.customer_id) if funds.customer_id else None,
            amount_minor=funds.amount_minor,
            currency=funds.currency,
            received_at=funds.received_at,
            handled_at=funds.handled_at,
            handled_by_id=(
                str(funds.handled_by_id) if funds.handled_by_id else None
            ),
            note=funds.note,
        )
