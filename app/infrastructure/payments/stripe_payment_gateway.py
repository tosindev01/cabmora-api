"""Stripe, over httpx, no SDK.

The same choice as `MailtrapEmailSender`, for the same reason: the port asks
for two things — start a hosted checkout, verify a signed callback — and both
are a form POST and an HMAC. An SDK would add a dependency, a release cadence
and a second way to configure credentials, in exchange for code this file
already contains.

**What the reference is.** `HostedCheckout.reference` is the Checkout Session
id (`cs_...`), not the PaymentIntent. With Checkout the PaymentIntent does not
exist until the customer actually pays, so there is nothing else to store at
the moment the link is handed over — and a reference that is null until payment
cannot be matched to an invoice when payment arrives.
"""

import hashlib
import hmac
import json
import logging
import time
from uuid import UUID

import httpx

from app.core.exceptions import DomainError
from app.domain.services.payment_gateway import (
    BankTransferFunding,
    GatewayCredit,
    GatewayEvent,
    HostedCheckout,
    PaymentGateway,
)

logger = logging.getLogger(__name__)

API = "https://api.stripe.com/v1"

#: How old a signed callback may be. Stripe's own default, and the reason it
#: exists: without it a signature captured once stays valid for ever, and a
#: replayed body marks an invoice paid again.
TOLERANCE_SECONDS = 300

#: The one event that means money arrived. `checkout.session.completed` fires
#: for the session we created and carries its id, which is what `reference`
#: holds. Other events are parsed and reported as not-succeeded rather than
#: rejected — Stripe sends whatever the dashboard is subscribed to, and an
#: endpoint that errors on the uninteresting ones looks broken to Stripe and
#: gets retried for ever.
PAID = "checkout.session.completed"

#: The bank-transfer counterpart. A transfer settles days after it is started,
#: so there is no session to complete — Stripe reconciles the money against the
#: PaymentIntent we opened and tells us about that instead.
INTENT_PAID = "payment_intent.succeeded"
INTENT_FAILED = "payment_intent.payment_failed"

#: GB sort-code-and-account-number transfers. Stripe splits this per country;
#: the capability is `gb_bank_transfer_payments` and it is granted separately
#: from card payments, so this path can be code-complete and still refused at
#: runtime until it is turned on in the Dashboard.
GB_BANK_TRANSFER = "gb_bank_transfer"

#: Money landed in a customer's balance that Stripe could not apply to any
#: open payment. Not a failure at Stripe's end — an underpayment, or a
#: transfer that arrived before the invoice did. It is reported once, and if
#: nothing listens the money is only visible in Stripe's own dashboard.
FUNDS_AVAILABLE = "cash_balance.funds_available"


class StripePaymentGateway(PaymentGateway):
    def __init__(self, *, secret_key: str, webhook_secret: str) -> None:
        self._secret_key = secret_key
        self._webhook_secret = webhook_secret

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
        # Form-encoded with Stripe's bracket syntax for nested fields; it does
        # not accept JSON bodies.
        form = {
            "mode": "payment",
            "success_url": success_url,
            "cancel_url": cancel_url,
            "line_items[0][quantity]": "1",
            "line_items[0][price_data][currency]": currency.lower(),
            "line_items[0][price_data][unit_amount]": str(amount_minor),
            "line_items[0][price_data][product_data][name]": description,
            # Carried so a webhook can be traced back to an invoice by hand if
            # it ever has to be. The reference is what the code matches on.
            "metadata[invoice_id]": str(invoice_id),
            "payment_intent_data[metadata][invoice_id]": str(invoice_id),
        }
        headers = {
            "Authorization": f"Bearer {self._secret_key}",
            # Stripe deduplicates on this key, so a retried request cannot
            # create a second session — and therefore cannot take the money
            # twice. Keyed on the invoice and the amount, because a part
            # payment of a different amount is a genuinely different attempt.
            "Idempotency-Key": f"invoice-{invoice_id}-{amount_minor}",
        }

        async with httpx.AsyncClient(timeout=20) as http:
            response = await http.post(
                f"{API}/checkout/sessions", data=form, headers=headers
            )

        if response.status_code >= 400:
            # Stripe's own sentence is far more useful than anything invented
            # here, and it is not shown to the customer.
            logger.error(
                "[stripe] checkout for invoice %s failed: %s %s",
                invoice_id, response.status_code, response.text[:500],
            )
            raise DomainError("The card payment could not be started.")

        body = response.json()
        url, reference = body.get("url"), body.get("id")
        if not url or not reference:
            logger.error("[stripe] checkout session missing url or id: %s", body)
            raise DomainError("The card payment could not be started.")
        return HostedCheckout(url=url, reference=reference)

    # ── bank transfer ────────────────────────────────────────────

    async def ensure_customer(
        self, *, user_id: UUID, email: str, name: str, existing: str | None
    ) -> str:
        if existing:
            return existing
        form = {"email": email, "name": name, "metadata[user_id]": str(user_id)}
        body = await self._post(
            "/customers",
            form,
            # Keyed on the person, so two transfers started at once cannot
            # produce two customers — and therefore cannot produce two
            # account numbers for one client, which would split their money.
            idempotency_key=f"customer-{user_id}",
            failure=f"[stripe] creating a customer for user {user_id} failed",
            message="The transfer details could not be prepared.",
        )
        customer_id = body.get("id")
        if not customer_id:
            logger.error("[stripe] customer response had no id: %s", body)
            raise DomainError("The transfer details could not be prepared.")
        return customer_id

    async def start_bank_transfer(
        self,
        *,
        customer_reference: str,
        invoice_id: UUID,
        amount_minor: int,
        currency: str,
        description: str,
    ) -> BankTransferFunding:
        form = {
            "amount": str(amount_minor),
            "currency": currency.lower(),
            "customer": customer_reference,
            "description": description,
            "payment_method_types[]": "customer_balance",
            "payment_method_data[type]": "customer_balance",
            "payment_method_options[customer_balance][funding_type]": "bank_transfer",
            "payment_method_options[customer_balance][bank_transfer][type]": (
                GB_BANK_TRANSFER
            ),
            # Confirmed immediately. Nothing is charged — with no balance to
            # draw on the intent goes to `requires_action`, and the action is
            # the customer making the transfer. That response is what carries
            # the account number, so without confirming there is nothing to
            # show them.
            "confirm": "true",
            "metadata[invoice_id]": str(invoice_id),
        }
        body = await self._post(
            "/payment_intents",
            form,
            idempotency_key=f"transfer-{invoice_id}-{amount_minor}",
            failure=f"[stripe] bank transfer for invoice {invoice_id} failed",
            message="The transfer details could not be prepared.",
        )
        return self._funding(body, invoice_id=invoice_id)

    @staticmethod
    def _funding(body: dict, *, invoice_id: UUID) -> BankTransferFunding:
        """Pull the account out of a confirmed intent, or refuse to guess.

        Every field is required. A half-read response would put a sort code
        with no account number in front of somebody about to send money, and
        an empty string renders as a blank line rather than as an error.
        """
        instructions = (body.get("next_action") or {}).get(
            "display_bank_transfer_instructions"
        ) or {}
        addresses = instructions.get("financial_addresses") or []
        account = next(
            (a.get("sort_code") for a in addresses if a.get("type") == "sort_code"),
            None,
        )
        reference, payment_reference = body.get("id"), instructions.get("reference")
        if not account or not reference or not payment_reference:
            logger.error(
                "[stripe] no GB account in the intent for invoice %s: %s",
                invoice_id, json.dumps(body)[:800],
            )
            # Nearly always the capability: `gb_bank_transfer_payments` is
            # granted separately, and without it Stripe confirms the intent
            # and returns no instructions rather than failing outright.
            raise DomainError("Bank transfer is not available at the moment.")
        holder = account.get("account_holder_name")
        sort_code, number = account.get("sort_code"), account.get("account_number")
        if not (holder and sort_code and number):
            logger.error("[stripe] GB account was incomplete: %s", account)
            raise DomainError("Bank transfer is not available at the moment.")
        return BankTransferFunding(
            reference=reference,
            account_holder_name=holder,
            sort_code=sort_code,
            account_number=number,
            payment_reference=payment_reference,
            amount_minor=int(instructions.get("amount_remaining") or 0),
            hosted_instructions_url=instructions.get("hosted_instructions_url"),
        )

    async def _post(
        self,
        path: str,
        form: dict[str, str],
        *,
        idempotency_key: str,
        failure: str,
        message: str,
    ) -> dict:
        """One POST, form-encoded, with Stripe's own error kept in the log.

        Stripe's sentence is far more useful than anything invented here, and
        it is never shown to the customer — it can name an unactivated
        capability or a malformed field, neither of which is their business.
        """
        headers = {
            "Authorization": f"Bearer {self._secret_key}",
            "Idempotency-Key": idempotency_key,
        }
        async with httpx.AsyncClient(timeout=20) as http:
            response = await http.post(f"{API}{path}", data=form, headers=headers)
        if response.status_code >= 400:
            logger.error("%s: %s %s", failure, response.status_code, response.text[:500])
            raise DomainError(message)
        return response.json()

    def parse_webhook(self, *, payload: bytes, signature: str) -> GatewayEvent:
        self._verify(payload=payload, signature=signature)

        body = json.loads(payload)
        event_type = body.get("type", "")
        obj = body.get("data", {}).get("object", {})

        if event_type == FUNDS_AVAILABLE:
            return self._credit(body, obj)

        if event_type in (INTENT_PAID, INTENT_FAILED):
            # A PaymentIntent carries `amount_received`, not `amount_total`,
            # and the two differ for a transfer that arrives short: reading
            # the wrong one would record money that is not there.
            return GatewayEvent(
                id=body.get("id", ""),
                type=event_type,
                reference=obj.get("id", ""),
                amount_minor=int(obj.get("amount_received") or 0),
                succeeded=event_type == INTENT_PAID,
            )

        return GatewayEvent(
            id=body.get("id", ""),
            type=event_type,
            reference=obj.get("id", ""),
            amount_minor=int(obj.get("amount_total") or 0),
            # Both conditions, not just the event name. A completed session
            # can still be unpaid — a bank transfer through Checkout completes
            # the session and settles days later — and marking that invoice
            # paid would hand over the work for money that never arrived.
            succeeded=event_type == PAID and obj.get("payment_status") == "paid",
        )

    @staticmethod
    def _credit(body: dict, obj: dict) -> GatewayEvent:
        """Reduce a cash-balance notice to the arrival it describes.

        Stripe reports the balance per currency as a map, and sends the event
        whenever that map changes — including when it goes *down*, because
        funds were applied to an invoice. Only a positive balance is money
        nobody has placed; the rest is the normal path doing its job, and
        recording it would fill the console with notices about payments that
        worked.
        """
        available = (obj.get("available") or {}) if isinstance(obj, dict) else {}
        currency, amount = next(
            ((c, int(v)) for c, v in available.items() if int(v or 0) > 0),
            (None, 0),
        )
        customer = obj.get("customer")
        if not currency or not customer:
            # Acknowledged, not recorded. Erroring would make Stripe retry an
            # event that will never be any different.
            return GatewayEvent(
                id=body.get("id", ""),
                type=body.get("type", ""),
                reference="",
                amount_minor=0,
                succeeded=False,
            )
        return GatewayEvent(
            id=body.get("id", ""),
            type=body.get("type", ""),
            # The event's own id. A cash balance has no id of its own, and the
            # event id is what makes recording this idempotent.
            reference=body.get("id", ""),
            amount_minor=amount,
            succeeded=False,
            credit=GatewayCredit(
                customer_reference=customer,
                amount_minor=amount,
                currency=currency.upper(),
            ),
        )

    def _verify(self, *, payload: bytes, signature: str) -> None:
        """Check Stripe's signature header, or refuse the body entirely.

        An unverified webhook is attacker-controlled input that marks invoices
        paid, so this runs before the body is even parsed as JSON.
        """
        parts = dict(
            piece.split("=", 1) for piece in signature.split(",") if "=" in piece
        )
        timestamp, sent = parts.get("t"), parts.get("v1")
        if not timestamp or not sent:
            raise DomainError("That callback was not signed.")

        try:
            age = time.time() - int(timestamp)
        except ValueError as exc:
            raise DomainError("That callback was not signed.") from exc
        if abs(age) > TOLERANCE_SECONDS:
            raise DomainError("That callback is too old to trust.")

        expected = hmac.new(
            self._webhook_secret.encode(),
            f"{timestamp}.".encode() + payload,
            hashlib.sha256,
        ).hexdigest()
        # Constant-time: a plain `==` leaks how much of the digest matched,
        # which is enough to forge one byte at a time.
        if not hmac.compare_digest(expected, sent):
            raise DomainError("That callback did not come from the gateway.")
