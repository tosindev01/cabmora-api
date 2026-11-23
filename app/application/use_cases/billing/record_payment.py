from datetime import datetime, timezone
from uuid import UUID

from app.application.use_cases.billing._access import assert_may_confirm_money, assert_may_manage
from app.application.use_cases.billing._money import money
from app.application.use_cases.notifications.notifier import Notifier
from app.core.exceptions import EntityNotFoundError, ValidationError
from app.domain.entities.invoice import (
    InvoiceStatus,
    Payment,
    PaymentMethod,
    PaymentStatus,
)
from app.domain.entities.user import User
from app.domain.repositories.invoice_repository import InvoiceRepository
from app.domain.repositories.project_repository import ProjectRepository

#: Card payments are never recorded by hand — they arrive from the gateway with
#: a reference we can verify. Allowing a manual STRIPE_CARD row would let
#: somebody assert a card payment that Stripe has no record of.
MANUAL_METHODS = {PaymentMethod.BANK_TRANSFER, PaymentMethod.CASH, PaymentMethod.OTHER}


class RecordPayment:
    """Log money the customer says they have sent, or that has been received.

    Lands PENDING. It only counts towards settlement once an administrator has
    confirmed it — see ConfirmPayment.

    Two ways in, one set of rules. `execute` is the team logging a payment
    they are expecting; `declare` is the client saying they have sent one.
    They differ only in who is allowed to call them, because everything that
    matters afterwards — the amount, the method, the PENDING landing, the
    administrator who has to confirm it — must be identical whoever typed it.
    A separate customer path would be a second place for those rules to live
    and a second place for them to drift.
    """

    def __init__(
        self,
        invoices: InvoiceRepository,
        projects: ProjectRepository,
        notifier: Notifier,
    ) -> None:
        self._invoices = invoices
        self._projects = projects
        self._notifier = notifier

    async def declare(
        self,
        *,
        actor: User,
        invoice_id: UUID,
        amount_minor: int,
        method: PaymentMethod,
        reference: str | None = None,
    ) -> Payment:
        """The client telling us they have paid.

        Worth having rather than making them email: a part payment sent to an
        account on a Friday is otherwise invisible until somebody reconciles
        the bank, and the client has no way to show they have done their bit.

        It changes nothing on its own. The row lands PENDING exactly as a
        staff-entered one does, so nothing is settled, no watermark comes off
        and no delivery gate opens until an administrator has seen the money
        arrive and confirmed it. That is the control, and it is the reason
        this is safe to expose to the person who owes the money.
        """
        invoice = await self._invoices.get_by_id(invoice_id)
        if invoice is None:
            raise EntityNotFoundError("Invoice not found")
        # "Not found" rather than "forbidden": confirming that somebody
        # else's invoice exists is itself a leak.
        if invoice.customer_id != actor.id:
            raise EntityNotFoundError("Invoice not found")
        return await self._record(
            invoice,
            amount_minor=amount_minor,
            method=method,
            reference=reference,
            recorded_by=actor.id,
            recorded_by_name=actor.full_name,
        )

    async def execute(
        self,
        *,
        actor: User,
        invoice_id: UUID,
        amount_minor: int,
        method: PaymentMethod,
        reference: str | None = None,
    ) -> Payment:
        invoice = await self._invoices.get_by_id(invoice_id)
        if invoice is None:
            raise EntityNotFoundError("Invoice not found")
        assert_may_manage(actor, invoice, await self._projects.get_by_id(invoice.project_id))

        return await self._record(
            invoice,
            amount_minor=amount_minor,
            method=method,
            reference=reference,
            recorded_by=actor.id,
            recorded_by_name=actor.full_name,
        )

    async def _record(
        self,
        invoice,
        *,
        amount_minor: int,
        method: PaymentMethod,
        reference: str | None,
        recorded_by: UUID,
        #: For the console's bell. The name, not another user lookup — both
        #: callers already hold the actor.
        recorded_by_name: str,
    ) -> Payment:
        """Everything that is true of a payment however it was entered."""
        if invoice.status is not InvoiceStatus.ISSUED:
            raise ValidationError("Only an issued invoice can take a payment.")
        if method not in MANUAL_METHODS:
            raise ValidationError(
                "Card payments are recorded by the gateway, not by hand."
            )
        if amount_minor <= 0:
            raise ValidationError("A payment must be for a positive amount.")
        if amount_minor > invoice.due_minor:
            raise ValidationError(
                f"That is more than the {invoice.due_minor} still outstanding."
            )

        payment = await self._invoices.add_payment(
            Payment(
                invoice_id=invoice.id,
                amount_minor=amount_minor,
                method=method,
                # Always. There is no path through this class that produces a
                # confirmed payment, which is what makes it safe to let the
                # person who owes the money call it.
                status=PaymentStatus.PENDING,
                reference=reference,
                recorded_by_id=recorded_by,
            )
        )
        # A pending payment is work the office owes somebody: until it is
        # confirmed the client is told nothing and the invoice still reads as
        # outstanding. Before this it sat in a table waiting to be noticed.
        await self._notifier.payment_declared(
            invoice_id=invoice.id,
            number=invoice.number or "",
            amount=money(amount_minor, invoice.currency),
            payer_name=recorded_by_name,
            actor_id=recorded_by,
        )
        return payment


class ConfirmPayment:
    """Declare that the money actually arrived. Administrators only."""

    def __init__(self, invoices: InvoiceRepository) -> None:
        self._invoices = invoices

    async def execute(self, *, actor: User, payment_id: UUID) -> Payment:
        assert_may_confirm_money(actor, "confirm a payment")
        payment = await self._invoices.get_payment(payment_id)
        if payment is None:
            raise EntityNotFoundError("Payment not found")
        if payment.status is PaymentStatus.CONFIRMED:
            raise ValidationError("This payment is already confirmed.")

        payment.status = PaymentStatus.CONFIRMED
        payment.confirmed_by_id = actor.id
        payment.confirmed_at = datetime.now(timezone.utc)
        return await self._invoices.update_payment(payment)
