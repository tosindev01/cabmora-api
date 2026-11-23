import hashlib
import json
from uuid import UUID, uuid4

from app.core.exceptions import DomainError
from app.domain.services.payment_gateway import (
    BankTransferFunding,
    GatewayCredit,
    GatewayEvent,
    HostedCheckout,
    PaymentGateway,
)


class FakePaymentGateway(PaymentGateway):
    """A gateway that takes no money, for building against before Stripe keys.

    The counterpart to `LoggingEmailSender`. It returns a checkout URL pointing
    at a local stub so the whole flow — start checkout, come back, receive a
    webhook, settle the invoice — is exercisable end to end with no account and
    no network.

    It must never be reachable outside local: `get_payment_gateway` refuses to
    return it when ENVIRONMENT is anything else. An invoice marked paid by a
    gateway that moved no money is worse than an outage.
    """

    #: Stand-in for Stripe's signing secret so the verification path is real code.
    SECRET = "fake-signing-secret"

    async def start_checkout(
        self,
        *,
        invoice_id: UUID,
        amount_minor: int,
        currency: str,
        description: str,
        success_url: str,
        cancel_url: str,
    ) -> HostedCheckout:
        reference = f"pi_fake_{uuid4().hex[:24]}"
        return HostedCheckout(
            url=f"/dev/checkout?reference={reference}&amount={amount_minor}",
            reference=reference,
        )

    async def ensure_customer(
        self, *, user_id: UUID, email: str, name: str, existing: str | None
    ) -> str:
        # Derived from the id rather than random, so re-running a flow locally
        # does not quietly issue the same person a second customer — the one
        # mistake this path must not be able to teach by example.
        return existing or f"cus_fake_{user_id.hex[:20]}"

    async def start_bank_transfer(
        self,
        *,
        customer_reference: str,
        invoice_id: UUID,
        amount_minor: int,
        currency: str,
        description: str,
    ) -> BankTransferFunding:
        # Obviously unreal numbers. A plausible-looking sort code on a local
        # screen is one screenshot away from somebody actually sending money
        # to it.
        return BankTransferFunding(
            reference=f"pi_fake_{uuid4().hex[:24]}",
            account_holder_name="Cabmora Media Ltd (test)",
            sort_code="00-00-00",
            account_number="00000000",
            payment_reference=f"FAKE-{str(invoice_id)[:8].upper()}",
            amount_minor=amount_minor,
            hosted_instructions_url=None,
        )

    def sign(self, payload: bytes) -> str:
        """Produce the signature `parse_webhook` will accept — for tests."""
        return hashlib.sha256(self.SECRET.encode() + payload).hexdigest()

    def parse_webhook(self, *, payload: bytes, signature: str) -> GatewayEvent:
        # Constant-time comparison, matching what the real adapter must do — a
        # signature check that leaks timing is not a signature check.
        import hmac

        if not hmac.compare_digest(signature, self.sign(payload)):
            raise DomainError("Webhook signature does not match.")

        body = json.loads(payload)
        # A `credit` key means money the gateway could not place, the same
        # shape the real adapter produces from `cash_balance.funds_available`.
        # Modelled here rather than only there because otherwise the whole
        # unplaced-funds path is unreachable without Stripe keys, and an
        # untestable path is one that rots.
        credit = body.get("credit")
        return GatewayEvent(
            id=body["id"],
            type=body["type"],
            reference=body["id"] if credit else body["reference"],
            amount_minor=(
                credit["amount_minor"] if credit else body["amount_minor"]
            ),
            succeeded=body["type"] == "payment_intent.succeeded",
            credit=(
                GatewayCredit(
                    customer_reference=credit["customer_reference"],
                    amount_minor=credit["amount_minor"],
                    currency=credit["currency"],
                )
                if credit
                else None
            ),
        )
