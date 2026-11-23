"""Money that arrived and matched nothing.

The failure this exists to prevent is silence. A client transfers before the
invoice is raised, or sends ninety pounds short; the gateway holds the money
against their customer record and settles nothing; the invoice goes on saying
unpaid. Every part of that is working as designed, and the net effect is that
only the gateway's own dashboard knows — which nobody at Cabmora opens daily.
"""

import json
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.core.security import hash_password
from app.domain.entities.unmatched_funds import UnmatchedFunds
from app.domain.entities.user import User, UserRole
from app.infrastructure.database import SessionFactory
from app.infrastructure.payments.fake_payment_gateway import FakePaymentGateway
from app.infrastructure.payments.stripe_payment_gateway import StripePaymentGateway
from app.infrastructure.repositories.unmatched_funds_repository_impl import (
    SqlAlchemyUnmatchedFundsRepository,
)
from app.infrastructure.repositories.user_repository_impl import SqlAlchemyUserRepository

PASSWORD = "password123"


async def _make(email: str, role: UserRole) -> User:
    async with SessionFactory() as session:
        user = await SqlAlchemyUserRepository(session).add(
            User(
                email=email,
                first_name=role.value.title(),
                last_name="Account",
                hashed_password=hash_password(PASSWORD),
                role=role,
            )
        )
        await session.commit()
        return user


async def _login(client, email: str) -> None:
    resp = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": PASSWORD}
    )
    assert resp.status_code == 200, resp.text


async def _record(**over) -> UnmatchedFunds:
    async with SessionFactory() as session:
        repo = SqlAlchemyUnmatchedFundsRepository(session)
        return await repo.record(
            UnmatchedFunds(
                reference=over.pop("reference", f"evt_{uuid4().hex[:12]}"),
                gateway_customer_reference=over.pop("customer_reference", "cus_x"),
                amount_minor=over.pop("amount_minor", 9000),
                currency=over.pop("currency", "GBP"),
                received_at=over.pop(
                    "received_at", datetime.now(timezone.utc)
                ),
                **over,
            )
        )


# --- recording -------------------------------------------------------------
@pytest.mark.anyio
async def test_the_same_arrival_is_only_recorded_once():
    reference = f"evt_{uuid4().hex[:12]}"
    first = await _record(reference=reference, amount_minor=9000)
    second = await _record(reference=reference, amount_minor=9000)
    # Two rows would read as eighteen thousand pounds of unplaced money where
    # there is nine. Stripe redelivers until acknowledged, so this is the
    # ordinary case rather than an edge one.
    assert first.id == second.id

    async with SessionFactory() as session:
        rows, total = await SqlAlchemyUnmatchedFundsRepository(session).list_all()
    assert len([r for r in rows if r.reference == reference]) == 1
    assert total >= 1


# --- handling --------------------------------------------------------------
def test_handling_requires_a_note():
    funds = UnmatchedFunds(
        reference="evt_1", gateway_customer_reference="cus_x",
        amount_minor=9000, currency="GBP",
    )
    with pytest.raises(ValueError):
        funds.mark_handled(by=uuid4(), note="   ")
    assert not funds.is_handled


def test_it_cannot_be_handled_twice():
    funds = UnmatchedFunds(
        reference="evt_1", gateway_customer_reference="cus_x",
        amount_minor=9000, currency="GBP",
    )
    funds.mark_handled(by=uuid4(), note="Called them; sending the rest.")
    with pytest.raises(ValueError):
        # The second note would overwrite the first, and the first is the one
        # written while anybody still remembered.
        funds.mark_handled(by=uuid4(), note="Something else.")


@pytest.mark.anyio
async def test_an_admin_can_mark_it_handled_and_it_leaves_the_working_list(client):
    admin = await _make("admin@x.com", UserRole.ADMIN)
    funds = await _record(amount_minor=9000)
    await _login(client, admin.email)

    outstanding = await client.get("/api/v1/admin/unmatched-funds?handled=false")
    assert outstanding.status_code == 200, outstanding.text
    assert any(row["id"] == str(funds.id) for row in outstanding.json()["items"])

    done = await client.post(
        f"/api/v1/admin/unmatched-funds/{funds.id}/handled",
        json={"note": "Rang them — invoice raised, Stripe applied it."},
    )
    assert done.status_code == 200, done.text
    assert done.json()["handled_at"] is not None

    after = await client.get("/api/v1/admin/unmatched-funds?handled=false")
    assert not any(row["id"] == str(funds.id) for row in after.json()["items"])
    # Still reachable. Deleting it on handling would throw away the only
    # record of what happened to somebody's money.
    kept = await client.get("/api/v1/admin/unmatched-funds?handled=true")
    assert any(row["id"] == str(funds.id) for row in kept.json()["items"])


@pytest.mark.anyio
async def test_an_empty_note_is_refused_by_the_api(client):
    admin = await _make("admin@x.com", UserRole.ADMIN)
    funds = await _record()
    await _login(client, admin.email)
    resp = await client.post(
        f"/api/v1/admin/unmatched-funds/{funds.id}/handled", json={"note": ""}
    )
    assert resp.status_code == 422


@pytest.mark.anyio
async def test_a_customer_cannot_see_the_list(client):
    customer = await _make("c@x.com", UserRole.CUSTOMER)
    await _record()
    await _login(client, customer.email)
    resp = await client.get("/api/v1/admin/unmatched-funds")
    assert resp.status_code in (401, 403)


# --- the webhook path ------------------------------------------------------
@pytest.mark.anyio
async def test_funds_with_no_invoice_are_recorded_and_the_office_is_told(client):
    admin = await _make("admin@x.com", UserRole.ADMIN)
    customer = await _make("c@x.com", UserRole.CUSTOMER)
    async with SessionFactory() as session:
        await SqlAlchemyUserRepository(session).set_stripe_customer_id(
            customer.id, "cus_known"
        )

    gateway = FakePaymentGateway()
    payload = json.dumps(
        {
            "id": f"evt_{uuid4().hex[:12]}",
            "type": "cash_balance.funds_available",
            "reference": "",
            "amount_minor": 0,
            "credit": {
                "customer_reference": "cus_known",
                "amount_minor": 9000,
                "currency": "GBP",
            },
        }
    ).encode()
    resp = await client.post(
        "/api/v1/webhooks/stripe",
        content=payload,
        headers={"stripe-signature": gateway.sign(payload)},
    )
    assert resp.status_code == 200

    await _login(client, admin.email)
    listed = await client.get("/api/v1/admin/unmatched-funds?handled=false")
    rows = [r for r in listed.json()["items"] if r["amount_minor"] == 9000]
    assert rows, listed.text
    # Attributed, because the account it landed in is the attribution.
    assert rows[0]["customer_id"] == str(customer.id)
    assert rows[0]["customer_name"]

    bell = await client.get("/api/v1/notifications")
    assert any(
        "arrived with no invoice" in n["title"] for n in bell.json()["items"]
    ), bell.text


@pytest.mark.anyio
async def test_unplaced_funds_never_settle_an_invoice(client):
    """The whole reason this is not a `Payment`.

    A row that counted towards settlement would mark the invoice paid and
    release the photographs for money nobody has reconciled.
    """
    admin = await _make("admin@x.com", UserRole.ADMIN)
    customer = await _make("c@x.com", UserRole.CUSTOMER)
    await _login(client, admin.email)
    project = await client.post(
        "/api/v1/admin/projects",
        json={
            "title": "Smith Wedding",
            "customer_id": str(customer.id),
            "event_type": "Wedding",
            "location": "Tuscany",
        },
    )
    invoice = await client.post(
        "/api/v1/admin/invoices",
        json={
            "project_id": project.json()["id"],
            "due_at": "2030-01-01T00:00:00+00:00",
            "line_items": [
                {"description": "Photography", "quantity": 1,
                 "unit_amount_minor": 9000}
            ],
        },
    )
    issued = await client.post(
        f"/api/v1/admin/invoices/{invoice.json()['id']}/issue"
    )
    invoice_id = issued.json()["id"]

    async with SessionFactory() as session:
        await SqlAlchemyUserRepository(session).set_stripe_customer_id(
            customer.id, "cus_settle"
        )

    gateway = FakePaymentGateway()
    payload = json.dumps(
        {
            "id": f"evt_{uuid4().hex[:12]}",
            "type": "cash_balance.funds_available",
            "reference": "",
            "amount_minor": 0,
            "credit": {
                "customer_reference": "cus_settle",
                "amount_minor": 9000,
                "currency": "GBP",
            },
        }
    ).encode()
    await client.post(
        "/api/v1/webhooks/stripe",
        content=payload,
        headers={"stripe-signature": gateway.sign(payload)},
    )

    after = (await client.get(f"/api/v1/admin/invoices/{invoice_id}")).json()
    assert after["paid_minor"] == 0
    assert after["settlement"] != "paid"
    assert after["payments"] == []


# --- reading Stripe's own event -------------------------------------------
def _balance_event(available: dict, customer: str | None = "cus_x") -> dict:
    return {
        "id": "evt_cash_1",
        "type": "cash_balance.funds_available",
        "data": {"object": {"customer": customer, "available": available}},
    }


def test_a_positive_balance_becomes_a_credit():
    event = StripePaymentGateway._credit(
        _balance_event({"gbp": 9000}), _balance_event({"gbp": 9000})["data"]["object"]
    )
    assert event.credit is not None
    assert event.credit.amount_minor == 9000
    assert event.credit.currency == "GBP"
    assert event.credit.customer_reference == "cus_x"
    # Never settles anything, whatever else it carries.
    assert event.succeeded is False


def test_a_zero_balance_is_acknowledged_and_not_recorded():
    """Stripe sends this event when the balance goes *down* too.

    That happens when funds are applied to an invoice — the normal path
    working. Recording it would fill the console with notices about payments
    that succeeded.
    """
    body = _balance_event({"gbp": 0})
    event = StripePaymentGateway._credit(body, body["data"]["object"])
    assert event.credit is None


def test_a_balance_with_no_customer_is_acknowledged_and_not_recorded():
    body = _balance_event({"gbp": 9000}, customer=None)
    event = StripePaymentGateway._credit(body, body["data"]["object"])
    assert event.credit is None
