from uuid import UUID

from app.core.exceptions import EntityNotFoundError, ValidationError
from app.domain.entities.invoice import (
    InvoiceStatus,
    Payment,
    PaymentMethod,
    PaymentStatus,
)
from app.domain.entities.user import User, UserRole
from app.domain.repositories.invoice_repository import InvoiceRepository
from app.domain.services.payment_gateway import HostedCheckout, PaymentGateway


class StartCheckout:
    """Begin a card payment for an invoice the customer owns."""

    def __init__(
        self, invoices: InvoiceRepository, gateway: PaymentGateway, public_base_url: str
    ) -> None:
        self._invoices = invoices
        self._gateway = gateway
        self._base = public_base_url.rstrip("/")

    async def execute(
        self, *, actor: User, invoice_id: UUID, amount_minor: int | None = None
    ) -> tuple[HostedCheckout, int]:
        invoice = await self._invoices.get_by_id(invoice_id)
        if invoice is None:
            raise EntityNotFoundError("Invoice not found")
        if actor.role is UserRole.CUSTOMER and invoice.customer_id != actor.id:
            raise EntityNotFoundError("Invoice not found")
        if invoice.status is not InvoiceStatus.ISSUED:
            raise ValidationError("This invoice cannot be paid.")

        amount = amount_minor or invoice.due_minor
        if amount <= 0:
            raise ValidationError("This invoice is already settled.")
        if amount > invoice.due_minor:
            raise ValidationError(
                f"That is more than the {invoice.due_minor} still outstanding."
            )

        checkout = await self._gateway.start_checkout(
            invoice_id=invoice.id,
            amount_minor=amount,
            currency=invoice.currency,
            description=f"Invoice {invoice.number}",
            # `/client/billing`, not `/billing`. The second is the creator's
            # own billing screen; a customer coming back from Stripe would
            # land on somebody else's page, which at best shows them nothing
            # of theirs and at worst reads as the payment having gone astray.
            success_url=f"{self._base}/client/billing?paid={invoice.id}",
            cancel_url=f"{self._base}/client/billing",
        )

        # Recorded PENDING now so the webhook has a row to find by reference.
        # It counts for nothing until the gateway confirms it.
        await self._invoices.add_payment(
            Payment(
                invoice_id=invoice.id,
                amount_minor=amount,
                method=PaymentMethod.STRIPE_CARD,
                status=PaymentStatus.PENDING,
                reference=checkout.reference,
            )
        )
        return checkout, amount
