from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.entities.invoice import (
    Invoice,
    InvoiceLineItem,
    InvoiceStatus,
    Payment,
    PaymentMethod,
    PaymentStatus,
    Refund,
    RefundStatus,
)
from app.infrastructure.database import Base


class InvoiceModel(Base):
    __tablename__ = "invoices"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    #: Unique and nullable: null while DRAFT, burned once at issue. The unique
    #: constraint is the guarantee an accountant actually cares about.
    number: Mapped[str | None] = mapped_column(String(32), nullable=True, unique=True)

    project_id: Mapped[str] = mapped_column(String(36), index=True)
    customer_id: Mapped[str] = mapped_column(String(36), index=True)
    issued_by_id: Mapped[str] = mapped_column(String(36), index=True)

    currency: Mapped[str] = mapped_column(String(3), default="GBP")
    status: Mapped[str] = mapped_column(String(20), default=InvoiceStatus.DRAFT.value, index=True)

    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    issued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    voided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    def to_entity(
        self,
        line_items: list[InvoiceLineItem] | None = None,
        payments: list[Payment] | None = None,
    ) -> Invoice:
        return Invoice(
            id=UUID(self.id),
            number=self.number,
            project_id=UUID(self.project_id),
            customer_id=UUID(self.customer_id),
            issued_by_id=UUID(self.issued_by_id),
            currency=self.currency,
            status=InvoiceStatus(self.status),
            due_at=self.due_at,
            issued_at=self.issued_at,
            voided_at=self.voided_at,
            notes=self.notes,
            line_items=line_items or [],
            payments=payments or [],
            created_at=self.created_at,
        )


class InvoiceLineItemModel(Base):
    __tablename__ = "invoice_line_items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    invoice_id: Mapped[str] = mapped_column(String(36), index=True)
    description: Mapped[str] = mapped_column(String(500))
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    #: Minor units. Integer, never Numeric-as-float — see the entity module.
    unit_amount_minor: Mapped[int] = mapped_column(Integer)
    position: Mapped[int] = mapped_column(Integer, default=0)

    def to_entity(self) -> InvoiceLineItem:
        return InvoiceLineItem(
            id=UUID(self.id),
            description=self.description,
            quantity=self.quantity,
            unit_amount_minor=self.unit_amount_minor,
        )


class PaymentModel(Base):
    __tablename__ = "payments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    invoice_id: Mapped[str] = mapped_column(String(36), index=True)
    amount_minor: Mapped[int] = mapped_column(Integer)
    method: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), default=PaymentStatus.PENDING.value, index=True)
    reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    recorded_by_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    confirmed_by_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    def to_entity(self, refunds: list[Refund] | None = None) -> Payment:
        return Payment(
            refunds=refunds or [],
            id=UUID(self.id),
            invoice_id=UUID(self.invoice_id),
            amount_minor=self.amount_minor,
            method=PaymentMethod(self.method),
            status=PaymentStatus(self.status),
            reference=self.reference,
            recorded_by_id=UUID(self.recorded_by_id) if self.recorded_by_id else None,
            confirmed_by_id=UUID(self.confirmed_by_id) if self.confirmed_by_id else None,
            confirmed_at=self.confirmed_at,
            created_at=self.created_at,
        )


class RefundModel(Base):
    """Money given back. A row per refund, not a flag on the payment.

    Several partial refunds against one payment are normal — a discount agreed
    after the fact, then a further goodwill gesture — and each needs its own
    amount, reason and author.
    """

    __tablename__ = "refunds"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    payment_id: Mapped[str] = mapped_column(String(36), index=True)
    amount_minor: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(String(500))
    issued_by_id: Mapped[str] = mapped_column(String(36), index=True)
    status: Mapped[str] = mapped_column(String(20), default=RefundStatus.PENDING.value, index=True)
    reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    def to_entity(self) -> Refund:
        return Refund(
            id=UUID(self.id),
            payment_id=UUID(self.payment_id),
            amount_minor=self.amount_minor,
            reason=self.reason,
            issued_by_id=UUID(self.issued_by_id),
            status=RefundStatus(self.status),
            reference=self.reference,
            created_at=self.created_at,
        )


class InvoiceNumberSequenceModel(Base):
    """One row per year, holding the next number to hand out.

    A counter row rather than `MAX(number) + 1`, because that races: two
    invoices issued in the same moment read the same maximum and both claim it.
    Handing numbers out from a row that can be locked makes the sequence the
    database's problem instead of the application's.
    """

    __tablename__ = "invoice_number_sequences"

    year: Mapped[int] = mapped_column(Integer, primary_key=True)
    next_value: Mapped[int] = mapped_column(Integer, default=1)


class StripeEventModel(Base):
    """Every Stripe webhook we have already handled.

    The entire point is the unique constraint on `stripe_event_id`. Stripe
    retries a delivery until it gets a 2xx, and a duplicate
    `payment_intent.succeeded` processed twice records the money twice. The
    handler inserts here first; a conflict means "already done, acknowledge and
    stop". There is no domain entity for this — it is transport bookkeeping,
    not something the business talks about.
    """

    __tablename__ = "stripe_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    stripe_event_id: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    event_type: Mapped[str] = mapped_column(String(100))
    payload: Mapped[str] = mapped_column(Text)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
