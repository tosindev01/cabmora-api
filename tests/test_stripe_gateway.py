"""Stripe, as far as it can be exercised without reaching Stripe.

The webhook path carries the risk: a callback that is believed without being
verified is attacker-controlled input that marks invoices paid, so most of
what is pinned here is the signature check and the conditions under which
money is treated as having arrived.
"""

import hashlib
import hmac
import json
import time

import pytest

from app.core.exceptions import DomainError
from app.infrastructure.payments.stripe_payment_gateway import (
    TOLERANCE_SECONDS,
    StripePaymentGateway,
)

SECRET = "whsec_test_secret"


def _gateway() -> StripePaymentGateway:
    return StripePaymentGateway(secret_key="sk_test_x", webhook_secret=SECRET)


def _signed(body: dict, *, at: int | None = None, secret: str = SECRET) -> tuple[bytes, str]:
    payload = json.dumps(body).encode()
    timestamp = at if at is not None else int(time.time())
    digest = hmac.new(
        secret.encode(), f"{timestamp}.".encode() + payload, hashlib.sha256
    ).hexdigest()
    return payload, f"t={timestamp},v1={digest}"


def _session(payment_status: str = "paid", event_type: str = "checkout.session.completed") -> dict:
    return {
        "id": "evt_123",
        "type": event_type,
        "data": {
            "object": {
                "id": "cs_test_abc",
                "amount_total": 180000,
                "payment_status": payment_status,
            }
        },
    }


def test_a_correctly_signed_payment_is_accepted():
    payload, signature = _signed(_session())
    event = _gateway().parse_webhook(payload=payload, signature=signature)

    assert event.id == "evt_123"
    assert event.reference == "cs_test_abc", "must match what checkout stored"
    assert event.amount_minor == 180000
    assert event.succeeded is True


def test_a_forged_signature_is_refused():
    payload, signature = _signed(_session(), secret="whsec_not_ours")
    with pytest.raises(DomainError):
        _gateway().parse_webhook(payload=payload, signature=signature)


def test_a_tampered_body_is_refused():
    """The amount is the obvious thing to change: sign a £1 session, send a
    £1,800 one."""
    payload, signature = _signed(_session())
    tampered = payload.replace(b"180000", b"100")
    with pytest.raises(DomainError):
        _gateway().parse_webhook(payload=tampered, signature=signature)


def test_an_old_callback_is_refused():
    """Without a tolerance window a signature captured once is valid for ever,
    and replaying the body settles the invoice again."""
    payload, signature = _signed(_session(), at=int(time.time()) - TOLERANCE_SECONDS - 60)
    with pytest.raises(DomainError):
        _gateway().parse_webhook(payload=payload, signature=signature)


def test_an_unsigned_callback_is_refused():
    with pytest.raises(DomainError):
        _gateway().parse_webhook(payload=b"{}", signature="")


def test_a_completed_but_unpaid_session_has_not_succeeded():
    """A bank transfer through Checkout completes the session and settles days
    later. Treating that as paid hands over the work for money that has not
    arrived."""
    payload, signature = _signed(_session(payment_status="unpaid"))
    event = _gateway().parse_webhook(payload=payload, signature=signature)
    assert event.succeeded is False


def test_an_unrelated_event_is_parsed_rather_than_rejected():
    """Stripe sends whatever the endpoint is subscribed to. Erroring on the
    uninteresting ones looks broken to Stripe and gets retried for ever."""
    payload, signature = _signed(_session(event_type="payment_intent.created"))
    event = _gateway().parse_webhook(payload=payload, signature=signature)
    assert event.succeeded is False
    assert event.type == "payment_intent.created"
