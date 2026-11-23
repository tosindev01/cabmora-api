from abc import ABC, abstractmethod
from datetime import datetime
from uuid import UUID

from app.domain.entities.invoice import (
    Invoice,
    InvoiceStatus,
    Payment,
    Refund,
    Settlement,
)


class InvoiceRepository(ABC):
    """Invoices, their payments and their refunds.

    One repository rather than three because they are a single aggregate: an
    invoice's settlement is computed from its payments, and a payment's net from
    its refunds, so loading one without the others gives an object that lies
    about how much is owed.
    """

    @abstractmethod
    async def add(self, invoice: Invoice) -> Invoice:
        """Create a draft with its line items in one transaction."""

    @abstractmethod
    async def get_by_id(self, invoice_id: UUID) -> Invoice | None:
        """Fully loaded — line items, payments, and each payment's refunds."""

    @abstractmethod
    async def update(self, invoice: Invoice) -> Invoice:
        """Persist the invoice and replace its line items."""

    @abstractmethod
    async def next_number(self, *, year: int) -> str:
        """Burn the next invoice number for `year`.

        Must be atomic. `MAX(number) + 1` races: two invoices issued in the same
        second get the same number, and the duplicate is only discovered when
        the unique index rejects it — or worse, on a customer's statement.
        """

    @abstractmethod
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
    ) -> list[Invoice]: ...

    @abstractmethod
    async def count_all(
        self,
        status: InvoiceStatus | None = None,
        settlement: Settlement | None = None,
        project_id: UUID | None = None,
        customer_id: UUID | None = None,
        issued_by_id: UUID | None = None,
        search: str | None = None,
    ) -> int: ...

    @abstractmethod
    async def totals_for_projects(
        self, project_ids: list[UUID]
    ) -> dict[UUID, tuple[int, int]]:
        """`{project_id: (billed_minor, paid_minor)}` for a page of projects.

        Billed counts issued invoices only — a draft is not a claim on
        anybody. Paid is net of settled refunds and counts confirmed payments
        only, because "the customer says they have paid" and "the money
        arrived" are different facts and a card must show the second.
        """
        ...

    @abstractmethod
    async def list_for_project(self, project_id: UUID) -> list[Invoice]:
        """Every invoice on a project — the source of the portal's rollup."""

    # ── payments ─────────────────────────────────────────────
    @abstractmethod
    async def add_payment(self, payment: Payment) -> Payment: ...

    @abstractmethod
    async def get_payment(self, payment_id: UUID) -> Payment | None: ...

    @abstractmethod
    async def get_payment_by_reference(self, reference: str) -> Payment | None:
        """Find the payment a gateway webhook is talking about."""

    @abstractmethod
    async def update_payment(self, payment: Payment) -> Payment: ...

    @abstractmethod
    async def list_payments(
        self,
        limit: int = 30,
        offset: int = 0,
        status: str | None = None,
        issued_by_id: UUID | None = None,
        project_id: UUID | None = None,
    ) -> list[Payment]:
        """Newest first.

        `issued_by_id` scopes to one creator's own invoices; `project_id` to
        one project, resolved through the invoices on it rather than a column
        on the payment.
        """

    @abstractmethod
    async def count_payments(
        self,
        status: str | None = None,
        issued_by_id: UUID | None = None,
        project_id: UUID | None = None,
    ) -> int: ...

    # ── refunds ──────────────────────────────────────────────
    @abstractmethod
    async def add_refund(self, refund: Refund) -> Refund: ...

    @abstractmethod
    async def get_refund(self, refund_id: UUID) -> Refund | None: ...

    @abstractmethod
    async def update_refund(self, refund: Refund) -> Refund: ...

    # ── gateway idempotency ──────────────────────────────────
    @abstractmethod
    async def claim_gateway_event(
        self, *, event_id: str, event_type: str, payload: str, at: datetime
    ) -> bool:
        """Record a webhook as ours to handle. False if we already have it.

        The whole defence against Stripe's retries. The caller does nothing
        unless this returns True, so a redelivered `payment_intent.succeeded`
        cannot record the money twice.
        """
