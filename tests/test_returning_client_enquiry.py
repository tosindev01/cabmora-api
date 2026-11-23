"""A client who already has an account booking another shoot.

The complaint was that an existing client clicking Bookings was treated as a
cold lead. Conversion already reused an account whose **email address**
matched, which covers the common case and nothing else: a client signed in as
one address who types another into the form is the same person, and matching
on the address alone gave them a second account and a second invite to a
portal they were already looking at.

So the form records who submitted it when it knows, and conversion trusts
that over the typed address.
"""

from datetime import datetime, timezone

import pytest

from app.core.security import hash_password
from app.domain.entities.user import User, UserRole
from app.infrastructure.database import SessionFactory
from app.infrastructure.repositories.user_repository_impl import SqlAlchemyUserRepository

pytestmark = pytest.mark.asyncio

PASSWORD = "password123"
FORM = {
    "first_name": "Mary Jane", "last_name": "Watson",
    "event_type": "Christening",
    "message": "We would love you for the christening in March.",
}


async def _make(email: str, role: UserRole) -> User:
    async with SessionFactory() as session:
        user = await SqlAlchemyUserRepository(session).add(
            User(email=email, first_name="Mary Jane", last_name="Watson",
                 hashed_password=hash_password(PASSWORD), role=role)
        )
        await session.commit()
        return user


async def _login(client, email: str) -> None:
    await client.post("/api/v1/auth/logout")
    resp = await client.post("/api/v1/auth/login",
                             json={"email": email, "password": PASSWORD})
    assert resp.status_code == 200, resp.text


async def test_a_signed_in_client_is_recognised(client):
    customer = await _make("mj@example.com", UserRole.CUSTOMER)
    await _login(client, customer.email)

    made = await client.post("/api/v1/enquiries", json={**FORM, "email": customer.email})
    assert made.status_code == 201, made.text

    admin = await _make("admin@example.com", UserRole.ADMIN)
    await _login(client, admin.email)
    detail = (await client.get(f"/api/v1/admin/enquiries/{made.json()['id']}")).json()
    assert detail["customer_id"] == str(customer.id), "the console should say who this is"


async def test_a_stranger_is_still_a_stranger(client):
    """The form stays public. Most enquiries are from people with no account
    and must keep working without one."""
    made = await client.post("/api/v1/enquiries", json={**FORM, "email": "nobody@example.com"})
    assert made.status_code == 201, made.text

    admin = await _make("admin@example.com", UserRole.ADMIN)
    await _login(client, admin.email)
    detail = (await client.get(f"/api/v1/admin/enquiries/{made.json()['id']}")).json()
    assert detail["customer_id"] is None


async def test_a_different_address_still_reaches_the_same_account(client):
    """The case the email match could never catch.

    Signed in as mj@example.com, booking with mj@work.com. One person, one
    account — not a duplicate and not a second invite to a portal they are
    already signed in to.
    """
    customer = await _make("mj@example.com", UserRole.CUSTOMER)
    await _login(client, customer.email)
    made = await client.post("/api/v1/enquiries", json={**FORM, "email": "mj@work.com"})
    assert made.status_code == 201, made.text

    admin = await _make("admin@example.com", UserRole.ADMIN)
    await _login(client, admin.email)
    converted = await client.post(
        f"/api/v1/admin/enquiries/{made.json()['id']}/convert",
        json={"first_name": "Mary Jane", "last_name": "Watson", "title": "Christening"},
    )
    assert converted.status_code == 201, converted.text
    assert converted.json()["customer_id"] == str(customer.id)
    assert converted.json()["invite_url"] is None, "they already have an account"


async def test_staff_testing_the_form_are_not_recorded_as_the_customer(client):
    """An admin uses this form while checking the site works.

    Stamping them would convert into a project owned by the office, with the
    studio as its own client.
    """
    admin = await _make("admin@example.com", UserRole.ADMIN)
    await _login(client, admin.email)

    made = await client.post("/api/v1/enquiries", json={**FORM, "email": admin.email})
    assert made.status_code == 201, made.text
    detail = (await client.get(f"/api/v1/admin/enquiries/{made.json()['id']}")).json()
    assert detail["customer_id"] is None


async def test_a_lapsed_session_can_still_send_the_form(client):
    """Authentication is optional here, so a bad cookie must not refuse the
    enquiry — it is the one thing on the site that has to work for anybody."""
    made = await client.post(
        "/api/v1/enquiries",
        json={**FORM, "email": "nobody@example.com"},
        cookies={"cabmora_session": "not-a-real-token"},
    )
    assert made.status_code == 201, made.text
