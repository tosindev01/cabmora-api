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
from app.domain.repositories.user_repository import UserRepository
from app.domain.services.payment_gateway import BankTransferFunding, PaymentGateway


class StartBankTransfer:
    """Hand a customer an account the gateway will watch on their behalf.

    The sibling of `StartCheckout`, and the same guards in the same order, for
    a reason worth stating: the only difference between the two is how long
    the money takes to arrive. Both open a payment, both record it PENDING,
    and in both cases it counts for nothing until a verified webhook says so.

    The one thing this does that a card payment never needs is a customer. The
    account number the client is told to pay into is issued *to them*, and is
    how an incoming transfer is attributed — so there is no anonymous version
    of this flow, and the id has to outlive the request that created it.
    """

    def __init__(
        self,
        invoices: InvoiceRepository,
        users: UserRepository,
        gateway: PaymentGateway,
    ) -> None:
        self._invoices = invoices
        self._users = users
        self._gateway = gateway

    async def execute(
        self, *, actor: User, invoice_id: UUID, amount_minor: int | None = None
    ) -> tuple[BankTransferFunding, int]:
        invoice = await self._invoices.get_by_id(invoice_id)
        if invoice is None:
            raise EntityNotFoundError("Invoice not found")
        if actor.role is UserRole.CUSTOMER and invoice.customer_id != actor.id:
            # Not found rather than forbidden, matching `StartCheckout`:
            # "this invoice exists but is not yours" is a fact worth nobody's
            # while to confirm.
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

        payer = await self._payer(invoice, actor)
        customer_reference = await self._gateway.ensure_customer(
            user_id=payer.id,
            email=payer.email,
            name=payer.full_name,
            existing=payer.stripe_customer_id,
        )
        if customer_reference != payer.stripe_customer_id:
            # Written before the transfer is opened. If this request dies
            # between the two, the worst case is a customer with no payment
            # against it; the other order risks a second customer on the
            # retry, and therefore a second account number for one client.
            await self._users.set_stripe_customer_id(payer.id, customer_reference)

        funding = await self._gateway.start_bank_transfer(
            customer_reference=customer_reference,
            invoice_id=invoice.id,
            amount_minor=amount,
            currency=invoice.currency,
            description=f"Invoice {invoice.number}",
        )
        # PENDING, so the webhook has a row to find by reference when the
        # money lands — which may be days later. It counts for nothing until
        # the gateway confirms it.
        await self._invoices.add_payment(
            Payment(
                invoice_id=invoice.id,
                amount_minor=amount,
                method=PaymentMethod.STRIPE_BANK_TRANSFER,
                status=PaymentStatus.PENDING,
                reference=funding.reference,
            )
        )
        return funding, amount

    async def _payer(self, invoice, actor: User) -> User:
        """Whose account this is, which is not always who asked.

        An administrator may open a transfer on a client's behalf — over the
        phone, say. The account must still be issued to the client, or the
        money arrives attributed to a member of staff.
        """
        if invoice.customer_id == actor.id:
            return actor
        payer = await self._users.get_by_id(invoice.customer_id)
        if payer is None:
            raise EntityNotFoundError("The customer on this invoice no longer exists.")
        return payer
