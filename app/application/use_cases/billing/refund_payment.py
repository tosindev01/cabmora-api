from uuid import UUID

from app.application.use_cases.billing._access import assert_may_confirm_money, assert_may_manage
from app.core.exceptions import EntityNotFoundError, ValidationError
from app.domain.entities.invoice import Refund, RefundStatus
from app.domain.entities.user import User
from app.domain.repositories.invoice_repository import InvoiceRepository
from app.domain.repositories.project_repository import ProjectRepository


class RefundPayment:
    """Give money back. The guards live on the entity; this handles access."""

    def __init__(self, invoices: InvoiceRepository, projects: ProjectRepository) -> None:
        self._invoices = invoices
        self._projects = projects

    async def execute(
        self, *, actor: User, payment_id: UUID, amount_minor: int, reason: str
    ) -> Refund:
        payment = await self._invoices.get_payment(payment_id)
        if payment is None:
            raise EntityNotFoundError("Payment not found")
        invoice = await self._invoices.get_by_id(payment.invoice_id)
        if invoice is None:
            raise EntityNotFoundError("Invoice not found")
        assert_may_manage(actor, invoice, await self._projects.get_by_id(invoice.project_id))

        if not reason or not reason.strip():
            raise ValidationError("A refund needs a reason.")

        refund = payment.refund(
            amount_minor=amount_minor, reason=reason, issued_by_id=actor.id
        )
        return await self._invoices.add_refund(refund)


class ConfirmRefund:
    """The money has gone back. Administrators only, same control as payments."""

    def __init__(self, invoices: InvoiceRepository) -> None:
        self._invoices = invoices

    async def execute(self, *, actor: User, refund_id: UUID) -> Refund:
        assert_may_confirm_money(actor, "confirm a refund")
        refund = await self._invoices.get_refund(refund_id)
        if refund is None:
            raise EntityNotFoundError("Refund not found")
        if refund.status is RefundStatus.CONFIRMED:
            raise ValidationError("This refund is already confirmed.")
        refund.status = RefundStatus.CONFIRMED
        return await self._invoices.update_refund(refund)
