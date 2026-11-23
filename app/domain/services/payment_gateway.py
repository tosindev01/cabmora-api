from abc import ABC, abstractmethod
from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class HostedCheckout:
    """Where to send the customer, and how we recognise them coming back."""

    url: str
    #: The gateway's own id for this attempt — with Stripe, the Checkout
    #: Session (`cs_...`). Not the PaymentIntent: with hosted Checkout that
    #: does not exist until the customer actually pays, so there would be
    #: nothing to store at the moment the link is handed over. Kept on
    #: `Payment.reference` so a webhook can be matched to an invoice without
    #: trusting anything the browser sends back.
    reference: str


@dataclass(frozen=True)
class BankTransferFunding:
    """Where to send a transfer that the gateway itself will reconcile.

    Not the same shape as `BankTransferDetails` on the invoice renderer, and
    deliberately kept apart from it. That one is Cabmora's own account, the
    same for everybody, printed on a document. This is an account the gateway
    issued *for one customer*, which is the entire mechanism: the account the
    money lands in is how the gateway knows whose it is.

    `payment_reference` still matters even so. The gateway matches on the
    reference first and falls back to the exact amount, so a client who omits
    it and happens to owe the same as another client is a reconciliation that
    picks the wrong invoice.
    """

    #: The gateway's id for this attempt, stored on `Payment.reference`.
    reference: str
    account_holder_name: str
    sort_code: str
    account_number: str
    #: What the client must quote on the transfer.
    payment_reference: str
    amount_minor: int
    #: The gateway's own page showing these details, when it offers one. Worth
    #: linking rather than only rendering our own copy: it is authoritative,
    #: and it updates if the gateway ever reissues the account.
    hosted_instructions_url: str | None = None


@dataclass(frozen=True)
class GatewayCredit:
    """Money that arrived against a customer but against no payment.

    Carried on the event rather than returned from a second method because
    there is one webhook endpoint and one signature to verify: splitting the
    parse would mean two ways into the same door, and the one that forgets to
    verify is the one that marks invoices paid.
    """

    customer_reference: str
    amount_minor: int
    currency: str


@dataclass(frozen=True)
class GatewayEvent:
    """A verified, deduplicated message from the gateway."""

    id: str  #: Stripe's `evt_...` — the unique key that makes replay safe
    type: str
    #: Matches `HostedCheckout.reference`, so with Stripe this is the Checkout
    #: Session id too — `parse_webhook` reads it off the event's own object.
    #: It has to be the same id that was stored, or the payment cannot be
    #: found when the money arrives.
    reference: str
    amount_minor: int
    succeeded: bool
    #: Set instead of a payment when the gateway is reporting money it could
    #: not place. `reference` is then the credit's own id, not a payment's,
    #: and no invoice is settled by it.
    credit: GatewayCredit | None = None


class PaymentGateway(ABC):
    """Card payments, as an interface the application depends on.

    Same shape as `EmailSender`, for the same reason: use cases say what should
    happen and never learn which provider did it. Stripe is the settled choice
    (CLAUDE.md §4), but no use case imports it.

    **Two kinds of bank transfer, and they are not the same thing.** A transfer
    to the account printed on an invoice never touches a gateway: it is a
    `Payment` an administrator records once they have seen the money land.
    A transfer to a Stripe-issued account number does, because Stripe watches
    that account and settles the payment itself. Only the second is modelled
    here. Cash is still neither.

    This interface said the opposite until the `gb_bank_transfer_payments`
    capability was turned on, and the reasoning was sound while it was off —
    modelling an integration that does not exist is worse than leaving a gap.
    It exists now.
    """

    @abstractmethod
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
        """Begin a card payment for part or all of an invoice."""

    @abstractmethod
    async def ensure_customer(
        self, *, user_id: UUID, email: str, name: str, existing: str | None
    ) -> str:
        """The gateway's id for this person, creating one only if needed.

        A bank transfer has to be attributed to somebody before the money
        arrives — the account number *is* the attribution — so unlike a card
        payment there is no anonymous path. `existing` is passed back rather
        than looked up so the caller owns the record of it, and a gateway that
        has it already does no work.
        """

    @abstractmethod
    async def start_bank_transfer(
        self,
        *,
        customer_reference: str,
        invoice_id: UUID,
        amount_minor: int,
        currency: str,
        description: str,
    ) -> BankTransferFunding:
        """Open a transfer the gateway will settle by itself.

        Nothing is owed at this point and nothing has moved. This reserves the
        payment so the gateway knows what an incoming transfer is *for*, and
        hands back the account to send it to.
        """

    @abstractmethod
    def parse_webhook(self, *, payload: bytes, signature: str) -> GatewayEvent:
        """Verify a signed callback and reduce it to what the domain needs.

        Signature verification belongs here, not in the router: an unverified
        webhook body is attacker-controlled input that marks invoices paid.
        """
