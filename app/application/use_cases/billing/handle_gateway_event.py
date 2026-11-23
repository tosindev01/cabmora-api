import json
from datetime import datetime, timezone

from app.domain.entities.invoice import PaymentStatus
from app.domain.entities.unmatched_funds import UnmatchedFunds
from app.domain.repositories.invoice_repository import InvoiceRepository
from app.domain.repositories.unmatched_funds_repository import (
    UnmatchedFundsRepository,
)
from app.domain.repositories.user_repository import UserRepository
from app.domain.services.payment_gateway import PaymentGateway


class HandleGatewayEvent:
    """Settle a card payment from a verified webhook.

    Two defences, both required:

    1. The signature is checked by the gateway adapter before anything here
       runs. An unverified body is attacker-controlled input that marks invoices
       paid.
    2. The event id is claimed in the database first. Stripe retries until it
       gets a 2xx, so without this a redelivered `payment_intent.succeeded`
       records the money a second time.
    """

    def __init__(
        self,
        invoices: InvoiceRepository,
        gateway: PaymentGateway,
        funds: UnmatchedFundsRepository,
        users: UserRepository,
        notifier=None,
    ) -> None:
        self._invoices = invoices
        self._gateway = gateway
        self._funds = funds
        self._users = users
        self._notifier = notifier

    async def execute(self, *, payload: bytes, signature: str) -> bool:
        event = self._gateway.parse_webhook(payload=payload, signature=signature)

        claimed = await self._invoices.claim_gateway_event(
            event_id=event.id,
            event_type=event.type,
            payload=payload.decode("utf-8", "replace"),
            at=datetime.now(timezone.utc),
        )
        if not claimed:
            return False  # already handled; acknowledge and stop

        if event.credit is not None:
            await self._record_unplaced(event)
            return True

        payment = await self._invoices.get_payment_by_reference(event.reference)
        if payment is None:
            # Nothing to settle — a payment for another environment, or one we
            # never recorded. Kept in stripe_events either way, for the audit.
            return True

        payment.status = (
            PaymentStatus.CONFIRMED if event.succeeded else PaymentStatus.FAILED
        )
        if event.succeeded:
            payment.confirmed_at = datetime.now(timezone.utc)
        await self._invoices.update_payment(payment)
        return True

    async def _record_unplaced(self, event) -> None:
        """Money that landed against a customer and against no payment.

        Recorded rather than ignored, and announced rather than merely
        recorded. The client believes they have paid; the invoice says they
        have not; and unless somebody is told, the only place this exists is
        the gateway's own dashboard, which nobody at Cabmora opens daily.
        """
        credit = event.credit
        payer = await self._users.get_by_stripe_customer_id(credit.customer_reference)
        funds = await self._funds.record(
            UnmatchedFunds(
                reference=event.reference,
                gateway_customer_reference=credit.customer_reference,
                customer_id=payer.id if payer else None,
                amount_minor=credit.amount_minor,
                currency=credit.currency,
            )
        )
        # Announced unconditionally, which is safe because a redelivery never
        # reaches here: `claim_gateway_event` above returns early for an event
        # id already seen. `record` is idempotent as well, but that is the
        # second line of defence rather than the one doing the work.
        if self._notifier is not None:
            await self._notifier.funds_unmatched(
                funds_id=funds.id,
                amount=f"{credit.amount_minor / 100:,.2f} {credit.currency}",
                payer_name=payer.full_name if payer else "an unrecognised customer",
            )
