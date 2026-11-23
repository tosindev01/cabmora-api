"""Transfers the gateway reconciles for us.

The thing being guarded is attribution. A card payment is anonymous until it
succeeds; a bank transfer is attributed *before* the money moves, by which
account number the client was told to use. Get that wrong — issue a second
account, or issue one in the wrong person's name — and the money arrives
belonging to nobody, with no screen in the system that shows it.

Settlement itself is covered in `test_billing.py` and is deliberately not
repeated: by the time a webhook arrives these two paths are the same code.
"""

import json
from uuid import uuid4

import pytest

from app.core.exceptions import DomainError
from app.core.security import hash_password
from app.domain.entities.user import User, UserRole
from app.infrastructure.database import SessionFactory
from app.infrastructure.payments.fake_payment_gateway import FakePaymentGateway
from app.infrastructure.payments.stripe_payment_gateway import StripePaymentGateway
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


async def _stored_customer_id(user_id) -> str | None:
    async with SessionFactory() as session:
        user = await SqlAlchemyUserRepository(session).get_by_id(user_id)
        return user.stripe_customer_id if user else None


async def _issued_invoice(client, admin, customer) -> dict:
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
    assert project.status_code == 201, project.text
    invoice = await client.post(
        "/api/v1/admin/invoices",
        json={
            "project_id": project.json()["id"],
            "due_at": "2030-01-01T00:00:00+00:00",
            "line_items": [
                {
                    "description": "Wedding photography",
                    "quantity": 1,
                    "unit_amount_minor": 425000,
                }
            ],
        },
    )
    assert invoice.status_code == 201, invoice.text
    issued = await client.post(
        f"/api/v1/admin/invoices/{invoice.json()['id']}/issue"
    )
    assert issued.status_code == 200, issued.text
    return issued.json()


# --- issuing the account ---------------------------------------------------
@pytest.mark.anyio
async def test_a_transfer_records_a_pending_payment_against_the_invoice(client):
    admin = await _make("admin@x.com", UserRole.ADMIN)
    customer = await _make("c@x.com", UserRole.CUSTOMER)
    invoice = await _issued_invoice(client, admin, customer)

    await _login(client, customer.email)
    resp = await client.post(
        f"/api/v1/invoices/{invoice['id']}/bank-transfer", json={}
    )
    assert resp.status_code == 200, resp.text
    funding = resp.json()
    assert funding["sort_code"] and funding["account_number"]
    assert funding["payment_reference"]
    assert funding["amount_minor"] == 425000

    await _login(client, admin.email)
    after = (await client.get(f"/api/v1/admin/invoices/{invoice['id']}")).json()
    assert len(after["payments"]) == 1
    payment = after["payments"][0]
    assert payment["method"] == "stripe_bank_transfer"
    assert payment["status"] == "pending"
    assert payment["reference"] == funding["reference"]
    # The whole point of PENDING: an account number has been handed over and
    # nothing has moved. An invoice that settled here would release the
    # photographs for money nobody has sent.
    assert after["paid_minor"] == 0
    assert after["settlement"] != "paid"


@pytest.mark.anyio
async def test_the_customer_id_is_kept_and_never_issued_twice(client):
    admin = await _make("admin@x.com", UserRole.ADMIN)
    customer = await _make("c@x.com", UserRole.CUSTOMER)
    invoice = await _issued_invoice(client, admin, customer)

    assert await _stored_customer_id(customer.id) is None

    await _login(client, customer.email)
    first = await client.post(
        f"/api/v1/invoices/{invoice['id']}/bank-transfer", json={}
    )
    assert first.status_code == 200, first.text
    stored = await _stored_customer_id(customer.id)
    assert stored is not None

    second = await client.post(
        f"/api/v1/invoices/{invoice['id']}/bank-transfer",
        json={"amount_minor": 1000},
    )
    assert second.status_code == 200, second.text
    # Same customer, so the same account number. A second one would split this
    # client's money across two accounts, and only one of them is on a screen.
    assert await _stored_customer_id(customer.id) == stored


@pytest.mark.anyio
async def test_an_admin_opening_a_transfer_bills_the_client_not_themselves(client):
    admin = await _make("admin@x.com", UserRole.ADMIN)
    customer = await _make("c@x.com", UserRole.CUSTOMER)
    invoice = await _issued_invoice(client, admin, customer)

    resp = await client.post(
        f"/api/v1/invoices/{invoice['id']}/bank-transfer", json={}
    )
    assert resp.status_code == 200, resp.text

    assert await _stored_customer_id(customer.id) is not None
    # The account belongs to whoever the invoice is for. Issuing it against
    # the member of staff who clicked would attribute the client's money to
    # an employee.
    assert await _stored_customer_id(admin.id) is None


# --- who may ask -----------------------------------------------------------
@pytest.mark.anyio
async def test_a_customer_cannot_open_a_transfer_on_somebody_elses_invoice(client):
    admin = await _make("admin@x.com", UserRole.ADMIN)
    customer = await _make("c@x.com", UserRole.CUSTOMER)
    stranger = await _make("other@x.com", UserRole.CUSTOMER)
    invoice = await _issued_invoice(client, admin, customer)

    await _login(client, stranger.email)
    resp = await client.post(
        f"/api/v1/invoices/{invoice['id']}/bank-transfer", json={}
    )
    # 404 rather than 403: confirming the invoice exists is itself a leak.
    assert resp.status_code == 404
    assert await _stored_customer_id(stranger.id) is None


@pytest.mark.anyio
async def test_a_draft_invoice_cannot_be_paid(client):
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
    draft = await client.post(
        "/api/v1/admin/invoices",
        json={
            "project_id": project.json()["id"],
            "due_at": "2030-01-01T00:00:00+00:00",
            "line_items": [
                {"description": "Deposit", "quantity": 1, "unit_amount_minor": 5000}
            ],
        },
    )

    await _login(client, customer.email)
    resp = await client.post(
        f"/api/v1/invoices/{draft.json()['id']}/bank-transfer", json={}
    )
    assert resp.status_code == 422


@pytest.mark.anyio
async def test_a_transfer_cannot_exceed_what_is_outstanding(client):
    admin = await _make("admin@x.com", UserRole.ADMIN)
    customer = await _make("c@x.com", UserRole.CUSTOMER)
    invoice = await _issued_invoice(client, admin, customer)

    await _login(client, customer.email)
    resp = await client.post(
        f"/api/v1/invoices/{invoice['id']}/bank-transfer",
        json={"amount_minor": 425001},
    )
    assert resp.status_code == 422


# --- settlement ------------------------------------------------------------
@pytest.mark.anyio
async def test_the_intent_webhook_settles_the_transfer(client):
    admin = await _make("admin@x.com", UserRole.ADMIN)
    customer = await _make("c@x.com", UserRole.CUSTOMER)
    invoice = await _issued_invoice(client, admin, customer)

    await _login(client, customer.email)
    funding = (
        await client.post(f"/api/v1/invoices/{invoice['id']}/bank-transfer", json={})
    ).json()

    gateway = FakePaymentGateway()
    payload = json.dumps(
        {
            "id": "evt_transfer_1",
            "type": "payment_intent.succeeded",
            "reference": funding["reference"],
            "amount_minor": 425000,
        }
    ).encode()
    resp = await client.post(
        "/api/v1/webhooks/stripe",
        content=payload,
        headers={"stripe-signature": gateway.sign(payload)},
    )
    assert resp.status_code == 200

    await _login(client, admin.email)
    after = (await client.get(f"/api/v1/admin/invoices/{invoice['id']}")).json()
    assert after["paid_minor"] == 425000
    assert after["settlement"] == "paid"
    assert after["payments"][0]["status"] == "confirmed"


# --- reading Stripe's answer -----------------------------------------------
def _intent(**over) -> dict:
    body = {
        "id": "pi_123",
        "next_action": {
            "display_bank_transfer_instructions": {
                "amount_remaining": 425000,
                "reference": "CBM-9921",
                "hosted_instructions_url": "https://pay.stripe.com/x",
                "financial_addresses": [
                    {
                        "type": "sort_code",
                        "sort_code": {
                            "account_holder_name": "Cabmora Media Ltd",
                            "sort_code": "108800",
                            "account_number": "00012345",
                        },
                    }
                ],
            }
        },
    }
    body.update(over)
    return body


def test_a_complete_intent_yields_the_account():
    funding = StripePaymentGateway._funding(_intent(), invoice_id=uuid4())
    assert funding.reference == "pi_123"
    assert funding.sort_code == "108800"
    assert funding.account_number == "00012345"
    assert funding.payment_reference == "CBM-9921"
    assert funding.amount_minor == 425000


def test_an_intent_with_no_instructions_is_refused():
    """What Stripe returns when `gb_bank_transfer_payments` is not granted.

    It confirms the intent and simply omits the instructions rather than
    erroring, so without this check the client is shown a blank account.
    """
    with pytest.raises(DomainError):
        StripePaymentGateway._funding({"id": "pi_123"}, invoice_id=uuid4())


def test_a_half_filled_account_is_refused():
    broken = _intent()
    address = broken["next_action"]["display_bank_transfer_instructions"][
        "financial_addresses"
    ][0]
    del address["sort_code"]["account_number"]
    # A sort code with no account number renders as a blank line, not as an
    # error, in front of somebody about to send four thousand pounds.
    with pytest.raises(DomainError):
        StripePaymentGateway._funding(broken, invoice_id=uuid4())


def test_an_iban_only_account_is_refused():
    """A euro account for a GBP invoice is the wrong account, not a near miss."""
    wrong = _intent()
    wrong["next_action"]["display_bank_transfer_instructions"][
        "financial_addresses"
    ] = [{"type": "iban", "iban": {"iban": "GB33BUKB20201555555555"}}]
    with pytest.raises(DomainError):
        StripePaymentGateway._funding(wrong, invoice_id=uuid4())
