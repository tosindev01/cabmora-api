"""Admin user management. The guard matters as much as the behaviour."""

import pytest

from app.core.security import hash_password
from app.domain.entities.user import User, UserRole
from app.infrastructure.database import SessionFactory
from app.infrastructure.repositories.user_repository_impl import SqlAlchemyUserRepository

ADMIN = {"email": "admin@example.com", "password": "password123"}
CUSTOMER = {
    "email": "cust@example.com",
    "first_name": "Cus",
    "last_name": "Tomer",
    "password": "password123",
}


async def _seed_admin() -> User:
    """Created directly: no endpoint grants ADMIN, which is the whole problem
    `scripts/create_admin.py` exists to solve."""
    async with SessionFactory() as session:
        repo = SqlAlchemyUserRepository(session)
        user = await repo.add(
            User(
                email=ADMIN["email"],
                first_name="Ad",
                last_name="Min",
                hashed_password=hash_password(ADMIN["password"]),
                role=UserRole.ADMIN,
            )
        )
        await session.commit()
        return user


async def _login(client, email: str, password: str) -> None:
    resp = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": password}
    )
    assert resp.status_code == 200, resp.text


async def _register_customer(client) -> str:
    resp = await client.post("/api/v1/auth/register", json=CUSTOMER)
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


# --- the guard -------------------------------------------------------------


@pytest.mark.asyncio
async def test_listing_users_requires_a_session(client):
    assert (await client.get("/api/v1/admin/users")).status_code == 401


@pytest.mark.asyncio
async def test_a_customer_cannot_list_users(client):
    """The point of the namespace: a valid session is not an admin session."""
    await _register_customer(client)
    await _login(client, CUSTOMER["email"], CUSTOMER["password"])
    assert (await client.get("/api/v1/admin/users")).status_code == 403


# --- listing ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_admin_sees_every_account(client):
    await _seed_admin()
    await _register_customer(client)
    await _login(client, ADMIN["email"], ADMIN["password"])

    resp = await client.get("/api/v1/admin/users")
    assert resp.status_code == 200, resp.text
    emails = {u["email"] for u in resp.json()["items"]}
    assert {ADMIN["email"], CUSTOMER["email"]} <= emails


@pytest.mark.asyncio
async def test_listing_filters_by_role(client):
    await _seed_admin()
    await _register_customer(client)
    await _login(client, ADMIN["email"], ADMIN["password"])

    resp = await client.get("/api/v1/admin/users", params={"role": "admin"})
    assert resp.status_code == 200
    assert [u["email"] for u in resp.json()["items"]] == [ADMIN["email"]]


# --- updating --------------------------------------------------------------


@pytest.mark.asyncio
async def test_admin_promotes_a_customer_to_creator(client):
    """The approval path: nothing else in the system can produce a creator."""
    await _seed_admin()
    user_id = await _register_customer(client)
    await _login(client, ADMIN["email"], ADMIN["password"])

    resp = await client.patch(
        f"/api/v1/admin/users/{user_id}", json={"role": "creator"}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["role"] == "creator"


@pytest.mark.asyncio
async def test_suspending_a_user_kills_their_live_session(client):
    """Suspension must bite on the very next request, not at token expiry."""
    await _seed_admin()
    user_id = await _register_customer(client)

    # The customer signs in and holds a valid cookie.
    await _login(client, CUSTOMER["email"], CUSTOMER["password"])
    assert (await client.get("/api/v1/auth/me")).status_code == 200
    customer_cookies = dict(client.cookies)

    # An admin suspends them.
    await _login(client, ADMIN["email"], ADMIN["password"])
    resp = await client.patch(
        f"/api/v1/admin/users/{user_id}", json={"status": "suspended"}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "suspended"

    # That still-valid cookie must now be worthless.
    client.cookies.clear()
    for name, value in customer_cookies.items():
        client.cookies.set(name, value)
    assert (await client.get("/api/v1/auth/me")).status_code == 401


# --- the self-lockout guard ------------------------------------------------


@pytest.mark.asyncio
async def test_an_admin_cannot_remove_their_own_role(client):
    admin = await _seed_admin()
    await _login(client, ADMIN["email"], ADMIN["password"])

    resp = await client.patch(
        f"/api/v1/admin/users/{admin.id}", json={"role": "customer"}
    )
    assert resp.status_code == 422, resp.text

    # And the refusal actually held.
    me = await client.get("/api/v1/auth/me")
    assert me.json()["role"] == "admin"


@pytest.mark.asyncio
async def test_an_admin_cannot_suspend_themselves(client):
    admin = await _seed_admin()
    await _login(client, ADMIN["email"], ADMIN["password"])

    resp = await client.patch(
        f"/api/v1/admin/users/{admin.id}", json={"status": "suspended"}
    )
    assert resp.status_code == 422, resp.text


# --- error shapes ----------------------------------------------------------


@pytest.mark.asyncio
async def test_updating_an_unknown_user_is_a_404(client):
    await _seed_admin()
    await _login(client, ADMIN["email"], ADMIN["password"])

    resp = await client.patch(
        "/api/v1/admin/users/00000000-0000-0000-0000-000000000000",
        json={"role": "creator"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_an_empty_patch_is_rejected(client):
    """A 200 that changed nothing reads as success to a caller that forgot its
    payload."""
    await _seed_admin()
    user_id = await _register_customer(client)
    await _login(client, ADMIN["email"], ADMIN["password"])

    resp = await client.patch(f"/api/v1/admin/users/{user_id}", json={})
    assert resp.status_code == 422


# --- acceptance ------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_creator_signup_lands_pending(client):
    resp = await client.post(
        "/api/v1/auth/register",
        json={**CUSTOMER, "email": "new@example.com", "account_type": "creator"},
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["role"] == "creator"
    assert resp.json()["status"] == "pending"


@pytest.mark.asyncio
async def test_a_customer_signup_also_lands_pending(client):
    """Every account is accepted by an admin, customers included."""
    resp = await client.post("/api/v1/auth/register", json=CUSTOMER)
    assert resp.json()["role"] == "customer"
    assert resp.json()["status"] == "pending"


@pytest.mark.asyncio
async def test_registration_cannot_ask_for_admin(client):
    """`account_type` is a two-value Literal, so this is unreachable."""
    resp = await client.post(
        "/api/v1/auth/register",
        json={**CUSTOMER, "email": "sneaky@example.com", "account_type": "admin"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_a_pending_creator_can_sign_in_but_not_act(client):
    """They need a session to see the gate; the gate is enforced server-side."""
    await client.post(
        "/api/v1/auth/register",
        json={**CUSTOMER, "email": "pend@example.com", "account_type": "creator"},
    )
    await _login(client, "pend@example.com", CUSTOMER["password"])

    assert (await client.get("/api/v1/auth/me")).status_code == 200
    assert (await client.get("/api/v1/auth/me")).json()["status"] == "pending"


@pytest.mark.asyncio
async def test_admin_accepts_a_pending_creator(client):
    await _seed_admin()
    reg = await client.post(
        "/api/v1/auth/register",
        json={**CUSTOMER, "email": "pend2@example.com", "account_type": "creator"},
    )
    user_id = reg.json()["id"]

    await _login(client, ADMIN["email"], ADMIN["password"])
    resp = await client.patch(
        f"/api/v1/admin/users/{user_id}", json={"status": "active"}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "active"


@pytest.mark.asyncio
async def test_the_pending_queue_is_filterable(client):
    await _seed_admin()
    await client.post(
        "/api/v1/auth/register",
        json={**CUSTOMER, "email": "q@example.com", "account_type": "creator"},
    )
    await _login(client, ADMIN["email"], ADMIN["password"])

    resp = await client.get("/api/v1/admin/users", params={"status": "pending"})
    assert resp.status_code == 200
    assert [u["email"] for u in resp.json()["items"]] == ["q@example.com"]


@pytest.mark.asyncio
async def test_stats_counts_only_what_exists(client):
    await _seed_admin()
    await _register_customer(client)
    await _login(client, ADMIN["email"], ADMIN["password"])

    resp = await client.get("/api/v1/admin/stats")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    users = body["users"]
    assert users["total"] == 2
    assert users["admins"] == 1
    assert users["customers"] == 1

    # Projects and enquiries are counted now that both entities exist, and read
    # zero here because none were created — a real zero, not a placeholder.
    assert body["projects"] == {"total": 0, "active": 0, "in_review": 0, "delivered": 0}
    assert body["enquiries"] == {"total": 0, "new": 0, "consultation_booked": 0}

    # Still no fabricated revenue or review figures. Revenue lives on
    # /admin/billing/stats because it has to net off refunds; reviews have no
    # entity at all, and a zero would read as "none pending" not "not built".
    assert set(body) == {"users", "projects", "enquiries"}


# --- pagination and search ------------------------------------------------


async def _seed_many(client, n: int) -> None:
    for i in range(n):
        await client.post(
            "/api/v1/auth/register",
            json={
                "email": f"bulk{i:02d}@example.com",
                "first_name": f"Bulk{i:02d}",
                "last_name": "Person",
                "password": "password123",
            },
        )


@pytest.mark.asyncio
async def test_total_describes_the_whole_result_set_not_the_page(client):
    """The footer count must not be the page length, or it reads as the truth."""
    await _seed_admin()
    await _seed_many(client, 12)
    await _login(client, ADMIN["email"], ADMIN["password"])

    resp = await client.get("/api/v1/admin/users", params={"limit": 5})
    body = resp.json()
    assert len(body["items"]) == 5
    assert body["total"] == 13  # 12 seeded + the admin
    assert body["limit"] == 5 and body["offset"] == 0


@pytest.mark.asyncio
async def test_offset_walks_the_pages_without_repeating(client):
    await _seed_admin()
    await _seed_many(client, 12)
    await _login(client, ADMIN["email"], ADMIN["password"])

    first = (await client.get("/api/v1/admin/users", params={"limit": 5})).json()
    second = (
        await client.get("/api/v1/admin/users", params={"limit": 5, "offset": 5})
    ).json()

    ids_a = {u["id"] for u in first["items"]}
    ids_b = {u["id"] for u in second["items"]}
    assert len(ids_b) == 5
    assert ids_a.isdisjoint(ids_b)


@pytest.mark.asyncio
async def test_total_respects_the_filter(client):
    """A grand total here would render "page 1 of 3" beside two rows."""
    await _seed_admin()
    await _seed_many(client, 4)
    await _login(client, ADMIN["email"], ADMIN["password"])

    resp = await client.get("/api/v1/admin/users", params={"role": "admin"})
    assert resp.json()["total"] == 1


@pytest.mark.asyncio
async def test_search_matches_a_full_name_across_both_columns(client):
    """`full_name` is derived, so this only works if the query concatenates."""
    await _seed_admin()
    await client.post(
        "/api/v1/auth/register",
        json={
            "email": "ada@example.com",
            "first_name": "Ada",
            "last_name": "Lovelace",
            "password": "password123",
        },
    )
    await _login(client, ADMIN["email"], ADMIN["password"])

    resp = await client.get("/api/v1/admin/users", params={"q": "ada lovelace"})
    assert [u["email"] for u in resp.json()["items"]] == ["ada@example.com"]

    by_email = await client.get("/api/v1/admin/users", params={"q": "ADA@EXAMPLE"})
    assert by_email.json()["total"] == 1


# --- detail ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_admin_fetches_one_user_by_id(client):
    await _seed_admin()
    user_id = await _register_customer(client)
    await _login(client, ADMIN["email"], ADMIN["password"])

    resp = await client.get(f"/api/v1/admin/users/{user_id}")
    assert resp.status_code == 200, resp.text
    assert resp.json()["email"] == CUSTOMER["email"]


@pytest.mark.asyncio
async def test_unknown_user_detail_is_a_404(client):
    await _seed_admin()
    await _login(client, ADMIN["email"], ADMIN["password"])
    resp = await client.get(
        "/api/v1/admin/users/00000000-0000-0000-0000-000000000000"
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_a_customer_cannot_read_another_account(client):
    await _register_customer(client)
    await _login(client, CUSTOMER["email"], CUSTOMER["password"])
    resp = await client.get(
        "/api/v1/admin/users/00000000-0000-0000-0000-000000000000"
    )
    assert resp.status_code == 403
