"""Invoices, payments and refunds through the API.

The cases that matter here are the ones where money can go wrong: a claimed
payment that has not landed, a refund that outruns the payment, a webhook
delivered twice, and a creator reaching for someone else's invoice.
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.core.security import hash_password
from app.domain.entities.user import User, UserRole
from app.infrastructure.database import SessionFactory
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


def _due(days: int = 14) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()


async def _project(client, customer_id, creator_id=None) -> dict:
    body = {
        "title": "Smith Wedding",
        "customer_id": str(customer_id),
        "event_type": "Wedding",
        "location": "Tuscany",
    }
    if creator_id:
        body["creator_id"] = str(creator_id)
    resp = await client.post("/api/v1/admin/projects", json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _invoice(client, project_id, amount_minor=425000, **over) -> dict:
    resp = await client.post(
        "/api/v1/admin/invoices",
        json={
            "project_id": str(project_id),
            "due_at": _due(),
            "line_items": [
                {"description": "Wedding photography", "quantity": 1,
                 "unit_amount_minor": amount_minor}
            ],
            **over,
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


# --- lifecycle -------------------------------------------------------------
@pytest.mark.anyio
async def test_a_draft_has_no_number_until_it_is_issued(client):
    admin = await _make("admin@x.com", UserRole.ADMIN)
    customer = await _make("c@x.com", UserRole.CUSTOMER)
    await _login(client, admin.email)
    project = await _project(client, customer.id)

    draft = await _invoice(client, project["id"])
    assert draft["number"] is None
    assert draft["status"] == "draft"
    assert draft["total_minor"] == 425000
    assert "issue" in draft["allowed_actions"]

    issued = await client.post(f"/api/v1/admin/invoices/{draft['id']}/issue")
    body = issued.json()
    assert issued.status_code == 200, issued.text
    assert body["number"].startswith("INV-")
    assert body["settlement"] == "unpaid"


@pytest.mark.anyio
async def test_numbers_are_sequential_and_never_reused(client):
    admin = await _make("admin@x.com", UserRole.ADMIN)
    customer = await _make("c@x.com", UserRole.CUSTOMER)
    await _login(client, admin.email)
    project = await _project(client, customer.id)

    numbers = []
    for _ in range(3):
        inv = await _invoice(client, project["id"])
        resp = await client.post(f"/api/v1/admin/invoices/{inv['id']}/issue")
        numbers.append(resp.json()["number"])

    assert len(set(numbers)) == 3
    tails = [int(n.split("-")[-1]) for n in numbers]
    assert tails == sorted(tails) and tails[-1] - tails[0] == 2

    # An abandoned draft must not burn a number.
    await _invoice(client, project["id"])
    inv = await _invoice(client, project["id"])
    resp = await client.post(f"/api/v1/admin/invoices/{inv['id']}/issue")
    assert int(resp.json()["number"].split("-")[-1]) == tails[-1] + 1


# --- the money -------------------------------------------------------------
@pytest.mark.anyio
async def test_a_claimed_transfer_is_not_money_until_an_admin_confirms(client):
    admin = await _make("admin@x.com", UserRole.ADMIN)
    customer = await _make("c@x.com", UserRole.CUSTOMER)
    await _login(client, admin.email)
    project = await _project(client, customer.id)
    inv = await _invoice(client, project["id"])
    await client.post(f"/api/v1/admin/invoices/{inv['id']}/issue")

    pay = await client.post(
        f"/api/v1/admin/invoices/{inv['id']}/payments",
        json={"amount_minor": 212500, "method": "bank_transfer", "reference": "FP-9931"},
    )
    assert pay.status_code == 201, pay.text
    assert pay.json()["status"] == "pending"

    after = (await client.get(f"/api/v1/admin/invoices/{inv['id']}")).json()
    assert after["paid_minor"] == 0, "a pending claim must not count as paid"
    assert after["settlement"] == "unpaid"

    confirmed = await client.post(f"/api/v1/admin/payments/{pay.json()['id']}/confirm")
    assert confirmed.status_code == 200, confirmed.text

    after = (await client.get(f"/api/v1/admin/invoices/{inv['id']}")).json()
    assert after["paid_minor"] == 212500
    assert after["due_minor"] == 212500
    assert after["settlement"] == "part_paid"


@pytest.mark.anyio
async def test_a_payment_cannot_exceed_what_is_outstanding(client):
    admin = await _make("admin@x.com", UserRole.ADMIN)
    customer = await _make("c@x.com", UserRole.CUSTOMER)
    await _login(client, admin.email)
    project = await _project(client, customer.id)
    inv = await _invoice(client, project["id"])
    await client.post(f"/api/v1/admin/invoices/{inv['id']}/issue")

    resp = await client.post(
        f"/api/v1/admin/invoices/{inv['id']}/payments",
        json={"amount_minor": 999999, "method": "cash"},
    )
    assert resp.status_code == 422
    assert isinstance(resp.json()["detail"], str)


@pytest.mark.anyio
async def test_a_card_payment_cannot_be_asserted_by_hand(client):
    admin = await _make("admin@x.com", UserRole.ADMIN)
    customer = await _make("c@x.com", UserRole.CUSTOMER)
    await _login(client, admin.email)
    project = await _project(client, customer.id)
    inv = await _invoice(client, project["id"])
    await client.post(f"/api/v1/admin/invoices/{inv['id']}/issue")

    resp = await client.post(
        f"/api/v1/admin/invoices/{inv['id']}/payments",
        json={"amount_minor": 1000, "method": "stripe_card"},
    )
    assert resp.status_code == 422
    assert "gateway" in resp.json()["detail"].lower()


# --- refunds ---------------------------------------------------------------
@pytest.mark.anyio
async def test_a_confirmed_refund_reduces_what_the_invoice_counts_as_paid(client):
    admin = await _make("admin@x.com", UserRole.ADMIN)
    customer = await _make("c@x.com", UserRole.CUSTOMER)
    await _login(client, admin.email)
    project = await _project(client, customer.id)
    inv = await _invoice(client, project["id"])
    await client.post(f"/api/v1/admin/invoices/{inv['id']}/issue")

    pay = (await client.post(
        f"/api/v1/admin/invoices/{inv['id']}/payments",
        json={"amount_minor": 425000, "method": "bank_transfer"},
    )).json()
    await client.post(f"/api/v1/admin/payments/{pay['id']}/confirm")
    assert (await client.get(f"/api/v1/admin/invoices/{inv['id']}")).json()["settlement"] == "paid"

    refund = await client.post(
        f"/api/v1/admin/payments/{pay['id']}/refunds",
        json={"amount_minor": 50000, "reason": "Album downgraded"},
    )
    assert refund.status_code == 201, refund.text

    # Still paid — a requested refund is not money until it is confirmed.
    assert (await client.get(f"/api/v1/admin/invoices/{inv['id']}")).json()["settlement"] == "paid"

    await client.post(f"/api/v1/admin/refunds/{refund.json()['id']}/confirm")
    after = (await client.get(f"/api/v1/admin/invoices/{inv['id']}")).json()
    assert after["paid_minor"] == 375000
    assert after["refunded_minor"] == 50000
    assert after["settlement"] == "part_paid"
    assert after["payments"][0]["refund_state"] == "partial"


@pytest.mark.anyio
async def test_a_refund_cannot_outrun_the_payment(client):
    admin = await _make("admin@x.com", UserRole.ADMIN)
    customer = await _make("c@x.com", UserRole.CUSTOMER)
    await _login(client, admin.email)
    project = await _project(client, customer.id)
    inv = await _invoice(client, project["id"])
    await client.post(f"/api/v1/admin/invoices/{inv['id']}/issue")
    pay = (await client.post(
        f"/api/v1/admin/invoices/{inv['id']}/payments",
        json={"amount_minor": 100000, "method": "cash"},
    )).json()
    await client.post(f"/api/v1/admin/payments/{pay['id']}/confirm")

    resp = await client.post(
        f"/api/v1/admin/payments/{pay['id']}/refunds",
        json={"amount_minor": 100001, "reason": "too much"},
    )
    assert resp.status_code == 422
    assert isinstance(resp.json()["detail"], str)


# --- access ----------------------------------------------------------------
@pytest.mark.anyio
async def test_a_creator_cannot_touch_another_creators_invoice(client):
    admin = await _make("admin@x.com", UserRole.ADMIN)
    customer = await _make("c@x.com", UserRole.CUSTOMER)
    mine = await _make("mine@x.com", UserRole.CREATOR)
    theirs = await _make("theirs@x.com", UserRole.CREATOR)

    await _login(client, admin.email)
    project = await _project(client, customer.id, creator_id=mine.id)
    inv = await _invoice(client, project["id"])

    await _login(client, theirs.email)
    assert (await client.get(f"/api/v1/admin/invoices/{inv['id']}")).status_code == 403
    assert (await client.post(f"/api/v1/admin/invoices/{inv['id']}/issue")).status_code == 403


@pytest.mark.anyio
async def test_a_creator_cannot_confirm_their_own_payment(client):
    """The control that makes creator self-billing safe."""
    admin = await _make("admin@x.com", UserRole.ADMIN)
    customer = await _make("c@x.com", UserRole.CUSTOMER)
    creator = await _make("cr@x.com", UserRole.CREATOR)

    await _login(client, admin.email)
    project = await _project(client, customer.id, creator_id=creator.id)

    await _login(client, creator.email)
    inv = await _invoice(client, project["id"])
    await client.post(f"/api/v1/admin/invoices/{inv['id']}/issue")
    pay = (await client.post(
        f"/api/v1/admin/invoices/{inv['id']}/payments",
        json={"amount_minor": 1000, "method": "bank_transfer"},
    )).json()

    resp = await client.post(f"/api/v1/admin/payments/{pay['id']}/confirm")
    assert resp.status_code == 403
    assert "administrator" in resp.json()["detail"].lower()


@pytest.mark.anyio
async def test_a_customer_never_sees_a_draft(client):
    admin = await _make("admin@x.com", UserRole.ADMIN)
    customer = await _make("c@x.com", UserRole.CUSTOMER)
    await _login(client, admin.email)
    project = await _project(client, customer.id)
    draft = await _invoice(client, project["id"])
    issued = await _invoice(client, project["id"], amount_minor=100000)
    await client.post(f"/api/v1/admin/invoices/{issued['id']}/issue")

    await _login(client, customer.email)
    listing = (await client.get("/api/v1/invoices")).json()
    assert listing["total"] == 1
    assert listing["items"][0]["id"] == issued["id"]
    assert (await client.get(f"/api/v1/invoices/{draft['id']}")).status_code == 404


@pytest.mark.anyio
async def test_the_invoice_pdf_can_be_read_or_kept(client):
    """Two intents, one document, and the caller says which.

    The button in the portal says "Download PDF". It served `inline`, so it
    opened a viewer instead — the same class of bug as a gallery link that
    displays a photograph rather than saving it, and the reason `save` is a
    parameter rather than a guess.
    """
    admin = await _make("admin@x.com", UserRole.ADMIN)
    customer = await _make("c@x.com", UserRole.CUSTOMER)
    await _login(client, admin.email)
    project = await _project(client, customer.id)
    invoice = await _invoice(client, project["id"])
    await client.post(f"/api/v1/admin/invoices/{invoice['id']}/issue")

    await _login(client, customer.email)

    reading = await client.get(f"/api/v1/invoices/{invoice['id']}/pdf")
    assert reading.status_code == 200, reading.text
    assert reading.headers["content-disposition"].startswith("inline;")

    keeping = await client.get(f"/api/v1/invoices/{invoice['id']}/pdf?save=1")
    assert keeping.status_code == 200, keeping.text
    assert keeping.headers["content-disposition"].startswith("attachment;")
    # Not compared byte for byte: the document is rendered per request, so
    # two renders differ in the id and timestamp PDF embeds. Same document,
    # same size, different bytes — which is the point of not storing it.
    assert keeping.content.startswith(b"%PDF-"), "a PDF either way"
    assert abs(len(keeping.content) - len(reading.content)) < 64


@pytest.mark.anyio
async def test_a_customer_cannot_read_someone_elses_invoice(client):
    admin = await _make("admin@x.com", UserRole.ADMIN)
    mine = await _make("mine@x.com", UserRole.CUSTOMER)
    other = await _make("other@x.com", UserRole.CUSTOMER)
    await _login(client, admin.email)
    project = await _project(client, mine.id)
    inv = await _invoice(client, project["id"])
    await client.post(f"/api/v1/admin/invoices/{inv['id']}/issue")

    await _login(client, other.email)
    assert (await client.get(f"/api/v1/invoices/{inv['id']}")).status_code == 404


# --- gateway ---------------------------------------------------------------
@pytest.mark.anyio
async def test_a_redelivered_webhook_does_not_take_the_money_twice(client):
    import json

    from app.infrastructure.payments.fake_payment_gateway import FakePaymentGateway

    admin = await _make("admin@x.com", UserRole.ADMIN)
    customer = await _make("c@x.com", UserRole.CUSTOMER)
    await _login(client, admin.email)
    project = await _project(client, customer.id)
    inv = await _invoice(client, project["id"])
    await client.post(f"/api/v1/admin/invoices/{inv['id']}/issue")

    await _login(client, customer.email)
    checkout = await client.post(f"/api/v1/invoices/{inv['id']}/checkout", json={})
    assert checkout.status_code == 200, checkout.text
    reference = checkout.json()["reference"]

    gateway = FakePaymentGateway()
    payload = json.dumps({
        "id": "evt_test_1",
        "type": "payment_intent.succeeded",
        "reference": reference,
        "amount_minor": 425000,
    }).encode()
    headers = {"stripe-signature": gateway.sign(payload)}

    for _ in range(3):
        resp = await client.post("/api/v1/webhooks/stripe", content=payload, headers=headers)
        assert resp.status_code == 200

    await _login(client, admin.email)
    after = (await client.get(f"/api/v1/admin/invoices/{inv['id']}")).json()
    assert after["paid_minor"] == 425000, "three deliveries must settle once"
    assert after["settlement"] == "paid"
    assert len(after["payments"]) == 1


@pytest.mark.anyio
async def test_a_forged_webhook_signature_is_refused(client):
    resp = await client.post(
        "/api/v1/webhooks/stripe",
        content=b'{"id":"evt_x","type":"payment_intent.succeeded","reference":"pi_x","amount_minor":1}',
        headers={"stripe-signature": "not-the-signature"},
    )
    # 400, not 422: the body is well-formed, it just is not from Stripe. This
    # is the one place a DomainError is deliberately left generic.
    assert resp.status_code == 400
    assert isinstance(resp.json()["detail"], str)


# --- dashboard + reporting -------------------------------------------------
@pytest.mark.anyio
async def test_dashboard_counts_come_from_the_database_not_a_page(client):
    """The bug this guards: counting a paginated list reports the page size."""
    admin = await _make("admin@x.com", UserRole.ADMIN)
    customer = await _make("c@x.com", UserRole.CUSTOMER)
    await _login(client, admin.email)

    for _ in range(3):
        await _project(client, customer.id)

    stats = (await client.get("/api/v1/admin/stats")).json()
    assert stats["projects"]["total"] == 3
    assert stats["projects"]["active"] == 3, "a draft project is not closed"
    assert stats["users"]["total"] == 2


@pytest.mark.anyio
async def test_monthly_revenue_is_net_of_refunds(client):
    admin = await _make("admin@x.com", UserRole.ADMIN)
    customer = await _make("c@x.com", UserRole.CUSTOMER)
    await _login(client, admin.email)
    project = await _project(client, customer.id)
    inv = await _invoice(client, project["id"])
    await client.post(f"/api/v1/admin/invoices/{inv['id']}/issue")

    pay = (await client.post(
        f"/api/v1/admin/invoices/{inv['id']}/payments",
        json={"amount_minor": 425000, "method": "bank_transfer"},
    )).json()

    # Pending money is not revenue.
    report = (await client.get("/api/v1/admin/reports/monthly?months=3")).json()
    assert sum(m["revenue_minor"] for m in report["months"]) == 0

    await client.post(f"/api/v1/admin/payments/{pay['id']}/confirm")
    report = (await client.get("/api/v1/admin/reports/monthly?months=3")).json()
    assert sum(m["revenue_minor"] for m in report["months"]) == 425000

    refund = (await client.post(
        f"/api/v1/admin/payments/{pay['id']}/refunds",
        json={"amount_minor": 125000, "reason": "Album downgraded"},
    )).json()
    await client.post(f"/api/v1/admin/refunds/{refund['id']}/confirm")

    report = (await client.get("/api/v1/admin/reports/monthly?months=3")).json()
    assert sum(m["revenue_minor"] for m in report["months"]) == 300000, (
        "gross revenue overstates the moment anything is refunded"
    )


@pytest.mark.anyio
async def test_a_quiet_month_is_present_with_zeroes(client):
    admin = await _make("admin@x.com", UserRole.ADMIN)
    await _login(client, admin.email)

    report = (await client.get("/api/v1/admin/reports/monthly?months=6")).json()
    assert len(report["months"]) == 6, "a gap would make a quiet month look missing"
    assert report["months"] == sorted(report["months"], key=lambda m: m["month"])
    assert report["currency"] == "GBP"


@pytest.mark.anyio
async def test_the_month_span_is_capped(client):
    admin = await _make("admin@x.com", UserRole.ADMIN)
    await _login(client, admin.email)
    report = (await client.get("/api/v1/admin/reports/monthly?months=500")).json()
    assert len(report["months"]) == 24, "a query string must not ask for a decade"


@pytest.mark.anyio
async def test_work_with_no_creator_is_attributed_to_cabmora(client):
    """The rule Project.creator_id documents, actually counted."""
    admin = await _make("admin@x.com", UserRole.ADMIN)
    customer = await _make("c@x.com", UserRole.CUSTOMER)
    creator = await _make("cr@x.com", UserRole.CREATOR)
    await _login(client, admin.email)

    await _project(client, customer.id)                       # in-house
    await _project(client, customer.id)                       # in-house
    await _project(client, customer.id, creator_id=creator.id)

    rows = (await client.get("/api/v1/admin/reports/creators")).json()["creators"]
    by_name = {r["name"]: r for r in rows}

    assert "Cabmora" in by_name, "unassigned work must not vanish"
    assert by_name["Cabmora"]["is_in_house"] is True
    assert by_name["Cabmora"]["creator_id"] is None
    assert by_name["Cabmora"]["projects_total"] == 2
    assert by_name["Creator Account"]["projects_total"] == 1

    # The panel and the dashboard tile must agree.
    stats = (await client.get("/api/v1/admin/stats")).json()
    assert sum(r["projects_total"] for r in rows) == stats["projects"]["total"]


@pytest.mark.anyio
async def test_the_in_house_row_exists_even_with_no_work(client):
    admin = await _make("admin@x.com", UserRole.ADMIN)
    await _login(client, admin.email)
    rows = (await client.get("/api/v1/admin/reports/creators")).json()["creators"]
    assert [r["name"] for r in rows] == ["Cabmora"]
    assert rows[0]["projects_total"] == 0


@pytest.mark.anyio
async def test_a_creator_with_no_work_still_appears(client):
    admin = await _make("admin@x.com", UserRole.ADMIN)
    await _make("idle@x.com", UserRole.CREATOR)
    await _login(client, admin.email)
    names = [r["name"] for r in (await client.get("/api/v1/admin/reports/creators")).json()["creators"]]
    assert "Creator Account" in names, "an onboarded partner with no work is worth seeing"


@pytest.mark.anyio
async def test_creator_revenue_counts_only_settled_issued_invoices(client):
    admin = await _make("admin@x.com", UserRole.ADMIN)
    customer = await _make("c@x.com", UserRole.CUSTOMER)
    await _login(client, admin.email)
    project = await _project(client, customer.id)

    await _invoice(client, project["id"])  # left as a draft
    rows = (await client.get("/api/v1/admin/reports/creators")).json()["creators"]
    assert rows[0]["revenue_minor"] == 0, "a draft was never sent to anyone"

    inv = await _invoice(client, project["id"])
    await client.post(f"/api/v1/admin/invoices/{inv['id']}/issue")
    rows = (await client.get("/api/v1/admin/reports/creators")).json()["creators"]
    assert rows[0]["revenue_minor"] == 0, "issued is not paid"

    pay = (await client.post(
        f"/api/v1/admin/invoices/{inv['id']}/payments",
        json={"amount_minor": 425000, "method": "cash"},
    )).json()
    await client.post(f"/api/v1/admin/payments/{pay['id']}/confirm")
    rows = (await client.get("/api/v1/admin/reports/creators")).json()["creators"]
    assert rows[0]["revenue_minor"] == 425000
