from datetime import datetime
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import EntityNotFoundError
from app.domain.entities.invoice import (
    Invoice,
    InvoiceLineItem,
    InvoiceStatus,
    Payment,
    PaymentStatus,
    Refund,
    RefundStatus,
    Settlement,
)
from app.domain.repositories.invoice_repository import InvoiceRepository
from app.infrastructure.models.invoice import (
    InvoiceLineItemModel,
    InvoiceModel,
    InvoiceNumberSequenceModel,
    PaymentModel,
    RefundModel,
    StripeEventModel,
)


class SqlAlchemyInvoiceRepository(InvoiceRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ── mapping ──────────────────────────────────────────────
    @staticmethod
    def _to_model(invoice: Invoice) -> InvoiceModel:
        return InvoiceModel(
            id=str(invoice.id),
            number=invoice.number,
            project_id=str(invoice.project_id),
            customer_id=str(invoice.customer_id),
            issued_by_id=str(invoice.issued_by_id),
            currency=invoice.currency,
            status=invoice.status.value,
            due_at=invoice.due_at,
            issued_at=invoice.issued_at,
            voided_at=invoice.voided_at,
            notes=invoice.notes,
            created_at=invoice.created_at,
        )

    @staticmethod
    def _payment_to_model(payment: Payment) -> PaymentModel:
        return PaymentModel(
            id=str(payment.id),
            invoice_id=str(payment.invoice_id),
            amount_minor=payment.amount_minor,
            method=payment.method.value,
            status=payment.status.value,
            reference=payment.reference,
            recorded_by_id=str(payment.recorded_by_id) if payment.recorded_by_id else None,
            confirmed_by_id=str(payment.confirmed_by_id) if payment.confirmed_by_id else None,
            confirmed_at=payment.confirmed_at,
            created_at=payment.created_at,
        )

    @staticmethod
    def _refund_to_model(refund: Refund) -> RefundModel:
        return RefundModel(
            id=str(refund.id),
            payment_id=str(refund.payment_id),
            amount_minor=refund.amount_minor,
            reason=refund.reason,
            issued_by_id=str(refund.issued_by_id),
            status=refund.status.value,
            reference=refund.reference,
            created_at=refund.created_at,
        )

    async def _hydrate(self, models: list[InvoiceModel]) -> list[Invoice]:
        """Load line items, payments and refunds for a page in four queries.

        Not one query per invoice: a page of 30 would be 91 round trips, which
        is the N+1 that makes a list endpoint feel broken.
        """
        if not models:
            return []
        ids = [m.id for m in models]

        items = (
            await self._session.execute(
                select(InvoiceLineItemModel)
                .where(InvoiceLineItemModel.invoice_id.in_(ids))
                .order_by(InvoiceLineItemModel.position)
            )
        ).scalars().all()

        payments = (
            await self._session.execute(
                select(PaymentModel).where(PaymentModel.invoice_id.in_(ids))
            )
        ).scalars().all()

        refunds = (
            await self._session.execute(
                select(RefundModel).where(
                    RefundModel.payment_id.in_([p.id for p in payments] or [""])
                )
            )
        ).scalars().all()

        refunds_by_payment: dict[str, list] = {}
        for r in refunds:
            refunds_by_payment.setdefault(r.payment_id, []).append(r.to_entity())

        items_by_invoice: dict[str, list] = {}
        for i in items:
            items_by_invoice.setdefault(i.invoice_id, []).append(i.to_entity())

        payments_by_invoice: dict[str, list] = {}
        for p in payments:
            payments_by_invoice.setdefault(p.invoice_id, []).append(
                p.to_entity(refunds=refunds_by_payment.get(p.id, []))
            )

        return [
            m.to_entity(
                line_items=items_by_invoice.get(m.id, []),
                payments=payments_by_invoice.get(m.id, []),
            )
            for m in models
        ]

    # ── invoices ─────────────────────────────────────────────
    async def add(self, invoice: Invoice) -> Invoice:
        self._session.add(self._to_model(invoice))
        for position, item in enumerate(invoice.line_items):
            self._session.add(
                InvoiceLineItemModel(
                    id=str(item.id),
                    invoice_id=str(invoice.id),
                    description=item.description,
                    quantity=item.quantity,
                    unit_amount_minor=item.unit_amount_minor,
                    position=position,
                )
            )
        await self._session.commit()
        return invoice

    async def get_by_id(self, invoice_id: UUID) -> Invoice | None:
        model = await self._session.get(InvoiceModel, str(invoice_id))
        if model is None:
            return None
        return (await self._hydrate([model]))[0]

    async def update(self, invoice: Invoice) -> Invoice:
        model = await self._session.get(InvoiceModel, str(invoice.id))
        if model is None:
            raise EntityNotFoundError("Invoice not found")

        model.number = invoice.number
        model.status = invoice.status.value
        model.due_at = invoice.due_at
        model.issued_at = invoice.issued_at
        model.voided_at = invoice.voided_at
        model.notes = invoice.notes
        model.currency = invoice.currency

        # Line items are replaced wholesale rather than diffed. They are only
        # editable while DRAFT, so there is nothing referencing them to break,
        # and a diff here would be more code and more ways to be wrong.
        existing = (
            await self._session.execute(
                select(InvoiceLineItemModel).where(
                    InvoiceLineItemModel.invoice_id == str(invoice.id)
                )
            )
        ).scalars().all()
        for row in existing:
            await self._session.delete(row)
        for position, item in enumerate(invoice.line_items):
            self._session.add(
                InvoiceLineItemModel(
                    id=str(item.id),
                    invoice_id=str(invoice.id),
                    description=item.description,
                    quantity=item.quantity,
                    unit_amount_minor=item.unit_amount_minor,
                    position=position,
                )
            )
        await self._session.commit()
        return await self.get_by_id(invoice.id)  # type: ignore[return-value]

    async def next_number(self, *, year: int) -> str:
        row = (
            await self._session.execute(
                select(InvoiceNumberSequenceModel)
                .where(InvoiceNumberSequenceModel.year == year)
                .with_for_update()
            )
        ).scalar_one_or_none()

        if row is None:
            row = InvoiceNumberSequenceModel(year=year, next_value=1)
            self._session.add(row)
            await self._session.flush()

        value = row.next_value
        row.next_value = value + 1
        await self._session.commit()
        return f"INV-{year}-{value:04d}"

    @staticmethod
    def _filters(
        status: InvoiceStatus | None,
        project_id: UUID | None,
        customer_id: UUID | None,
        issued_by_id: UUID | None,
        search: str | None,
    ) -> list:
        clauses = []
        if status is not None:
            clauses.append(InvoiceModel.status == status.value)
        if project_id is not None:
            clauses.append(InvoiceModel.project_id == str(project_id))
        if customer_id is not None:
            clauses.append(InvoiceModel.customer_id == str(customer_id))
        if issued_by_id is not None:
            clauses.append(InvoiceModel.issued_by_id == str(issued_by_id))
        if search and search.strip():
            term = f"%{search.strip().lower()}%"
            clauses.append(
                or_(
                    func.lower(InvoiceModel.number).like(term),
                    func.lower(InvoiceModel.notes).like(term),
                )
            )
        return clauses

    async def list_all(
        self,
        limit: int = 30,
        offset: int = 0,
        status: InvoiceStatus | None = None,
        settlement: Settlement | None = None,
        project_id: UUID | None = None,
        customer_id: UUID | None = None,
        issued_by_id: UUID | None = None,
        search: str | None = None,
    ) -> list[Invoice]:
        stmt = (
            select(InvoiceModel)
            .where(*self._filters(status, project_id, customer_id, issued_by_id, search))
            .order_by(InvoiceModel.created_at.desc())
        )
        # Settlement is derived from payments, so it cannot be a SQL predicate
        # without duplicating the rule in two places. Filtering it in Python
        # after hydration keeps one definition; the cost is that a settlement
        # filter pages over a wider window, which is fine at these volumes and
        # is flagged in the use case rather than hidden here.
        if settlement is None:
            stmt = stmt.limit(limit).offset(offset)
        models = (await self._session.execute(stmt)).scalars().all()
        invoices = await self._hydrate(list(models))
        if settlement is not None:
            invoices = [i for i in invoices if i.settlement is settlement]
            invoices = invoices[offset : offset + limit]
        return invoices

    async def count_all(
        self,
        status: InvoiceStatus | None = None,
        settlement: Settlement | None = None,
        project_id: UUID | None = None,
        customer_id: UUID | None = None,
        issued_by_id: UUID | None = None,
        search: str | None = None,
    ) -> int:
        clauses = self._filters(status, project_id, customer_id, issued_by_id, search)
        if settlement is None:
            return (
                await self._session.execute(
                    select(func.count()).select_from(InvoiceModel).where(*clauses)
                )
            ).scalar_one()
        models = (
            await self._session.execute(select(InvoiceModel).where(*clauses))
        ).scalars().all()
        return sum(1 for i in await self._hydrate(list(models)) if i.settlement is settlement)

    async def totals_for_projects(
        self, project_ids: list[UUID]
    ) -> dict[UUID, tuple[int, int]]:
        if not project_ids:
            return {}
        ids = [str(i) for i in project_ids]

        # Two aggregates rather than one. Joining line items and payments in a
        # single statement multiplies the rows against each other — an invoice
        # with three lines and two payments would count every line three times
        # and every payment twice. Classic fan-out, silently wrong.
        billed = {
            UUID(pid): total
            for pid, total in (
                await self._session.execute(
                    select(
                        InvoiceModel.project_id,
                        func.coalesce(
                            func.sum(
                                InvoiceLineItemModel.quantity
                                * InvoiceLineItemModel.unit_amount_minor
                            ),
                            0,
                        ),
                    )
                    .join(
                        InvoiceLineItemModel,
                        InvoiceLineItemModel.invoice_id == InvoiceModel.id,
                    )
                    .where(
                        InvoiceModel.project_id.in_(ids),
                        InvoiceModel.status == InvoiceStatus.ISSUED.value,
                    )
                    .group_by(InvoiceModel.project_id)
                )
            ).all()
        }

        refunded = (
            select(
                RefundModel.payment_id.label("payment_id"),
                func.sum(RefundModel.amount_minor).label("amount"),
            )
            .where(RefundModel.status == RefundStatus.CONFIRMED.value)
            .group_by(RefundModel.payment_id)
            .subquery()
        )

        paid = {
            UUID(pid): total
            for pid, total in (
                await self._session.execute(
                    select(
                        InvoiceModel.project_id,
                        func.coalesce(
                            func.sum(
                                PaymentModel.amount_minor
                                - func.coalesce(refunded.c.amount, 0)
                            ),
                            0,
                        ),
                    )
                    .join(PaymentModel, PaymentModel.invoice_id == InvoiceModel.id)
                    .outerjoin(refunded, refunded.c.payment_id == PaymentModel.id)
                    .where(
                        InvoiceModel.project_id.in_(ids),
                        InvoiceModel.status == InvoiceStatus.ISSUED.value,
                        PaymentModel.status == PaymentStatus.CONFIRMED.value,
                    )
                    .group_by(InvoiceModel.project_id)
                )
            ).all()
        }

        return {
            project_id: (billed.get(project_id, 0), paid.get(project_id, 0))
            for project_id in project_ids
        }

    async def list_for_project(self, project_id: UUID) -> list[Invoice]:
        models = (
            await self._session.execute(
                select(InvoiceModel).where(InvoiceModel.project_id == str(project_id))
            )
        ).scalars().all()
        return await self._hydrate(list(models))

    # ── payments ─────────────────────────────────────────────
    async def add_payment(self, payment: Payment) -> Payment:
        self._session.add(self._payment_to_model(payment))
        await self._session.commit()
        return payment

    async def _load_payment(self, model: PaymentModel) -> Payment:
        refunds = (
            await self._session.execute(
                select(RefundModel).where(RefundModel.payment_id == model.id)
            )
        ).scalars().all()
        return model.to_entity(refunds=[r.to_entity() for r in refunds])

    async def get_payment(self, payment_id: UUID) -> Payment | None:
        model = await self._session.get(PaymentModel, str(payment_id))
        return await self._load_payment(model) if model else None

    async def get_payment_by_reference(self, reference: str) -> Payment | None:
        model = (
            await self._session.execute(
                select(PaymentModel).where(PaymentModel.reference == reference)
            )
        ).scalar_one_or_none()
        return await self._load_payment(model) if model else None

    async def update_payment(self, payment: Payment) -> Payment:
        model = await self._session.get(PaymentModel, str(payment.id))
        if model is None:
            raise EntityNotFoundError("Payment not found")
        model.status = payment.status.value
        model.reference = payment.reference
        model.confirmed_by_id = (
            str(payment.confirmed_by_id) if payment.confirmed_by_id else None
        )
        model.confirmed_at = payment.confirmed_at
        await self._session.commit()
        return await self._load_payment(model)

    def _payment_filters(
        self,
        status: str | None,
        issued_by_id: UUID | None,
        project_id: UUID | None = None,
    ) -> list:
        """Shared by list and count so the page and its total agree."""
        clauses = []
        if project_id is not None:
            # Through the invoice: a payment belongs to a bill, and the bill
            # belongs to the project. Denormalising the project onto the
            # payment would be a second copy able to disagree with the first.
            clauses.append(
                PaymentModel.invoice_id.in_(
                    select(InvoiceModel.id).where(
                        InvoiceModel.project_id == str(project_id)
                    )
                )
            )
        if status:
            clauses.append(PaymentModel.status == status)
        if issued_by_id is not None:
            clauses.append(
                PaymentModel.invoice_id.in_(
                    select(InvoiceModel.id).where(
                        InvoiceModel.issued_by_id == str(issued_by_id)
                    )
                )
            )
        return clauses

    async def list_payments(
        self,
        limit: int = 30,
        offset: int = 0,
        status: str | None = None,
        issued_by_id: UUID | None = None,
        project_id: UUID | None = None,
    ) -> list[Payment]:
        models = (
            await self._session.execute(
                select(PaymentModel)
                .where(*self._payment_filters(status, issued_by_id, project_id))
                .order_by(PaymentModel.created_at.desc())
                .limit(limit)
                .offset(offset)
            )
        ).scalars().all()
        return [await self._load_payment(m) for m in models]

    async def count_payments(
        self,
        status: str | None = None,
        issued_by_id: UUID | None = None,
        project_id: UUID | None = None,
    ) -> int:
        return (
            await self._session.execute(
                select(func.count())
                .select_from(PaymentModel)
                .where(*self._payment_filters(status, issued_by_id))
            )
        ).scalar_one()

    # ── refunds ──────────────────────────────────────────────
    async def add_refund(self, refund: Refund) -> Refund:
        self._session.add(self._refund_to_model(refund))
        await self._session.commit()
        return refund

    async def get_refund(self, refund_id: UUID) -> Refund | None:
        model = await self._session.get(RefundModel, str(refund_id))
        return model.to_entity() if model else None

    async def update_refund(self, refund: Refund) -> Refund:
        model = await self._session.get(RefundModel, str(refund.id))
        if model is None:
            raise EntityNotFoundError("Refund not found")
        model.status = refund.status.value
        model.reference = refund.reference
        await self._session.commit()
        return model.to_entity()

    # ── gateway idempotency ──────────────────────────────────
    async def claim_gateway_event(
        self, *, event_id: str, event_type: str, payload: str, at: datetime
    ) -> bool:
        from uuid import uuid4

        self._session.add(
            StripeEventModel(
                id=str(uuid4()),
                stripe_event_id=event_id,
                event_type=event_type,
                payload=payload,
                received_at=at,
            )
        )
        try:
            await self._session.commit()
        except IntegrityError:
            # The unique index rejected it: this delivery is a retry of one we
            # have already handled. Let the caller acknowledge and do nothing.
            await self._session.rollback()
            return False
        return True
