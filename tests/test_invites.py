"""Admin-provisioned accounts and the invite that claims them."""

import pytest

from app.core.security import hash_password
from app.domain.entities.user import User, UserRole
from app.infrastructure.database import SessionFactory
from app.infrastructure.repositories.user_repository_impl import SqlAlchemyUserRepository

ADMIN = {"email": "admin@x.com", "password": "password123"}
NEW = {"email": "client@x.com", "first_name": "New", "last_name": "Client"}


async def _seed_admin() -> User:
    async with SessionFactory() as session:
        user = await SqlAlchemyUserRepository(session).add(
            User(
                email=ADMIN["email"], first_name="Ad", last_name="Min",
                hashed_password=hash_password(ADMIN["password"]), role=UserRole.ADMIN,
            )
        )
        await session.commit()
        return user


async def _login_admin(client) -> None:
    resp = await client.post("/api/v1/auth/login", json=ADMIN)
    assert resp.status_code == 200, resp.text


async def _provision(client) -> dict:
    resp = await client.post("/api/v1/admin/users", json=NEW)
    assert resp.status_code == 201, resp.text
    return resp.json()


@pytest.mark.asyncio
async def test_provisioned_accounts_skip_the_acceptance_queue(client):
    """An admin creating an account has already vetted them."""
    await _seed_admin()
    await _login_admin(client)
    await _provision(client)

    listing = await client.get("/api/v1/admin/users", params={"q": NEW["email"]})
    assert listing.json()["items"][0]["status"] == "active"


@pytest.mark.asyncio
async def test_an_unclaimed_account_cannot_be_signed_into(client):
    """It exists, but has no password until the invite is accepted."""
    await _seed_admin()
    await _login_admin(client)
    await _provision(client)

    resp = await client.post(
        "/api/v1/auth/login", json={"email": NEW["email"], "password": ""}
    )
    assert resp.status_code == 401
    resp = await client.post(
        "/api/v1/auth/login", json={"email": NEW["email"], "password": "anything123"}
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_accepting_the_invite_sets_a_password_and_signs_in(client):
    await _seed_admin()
    await _login_admin(client)
    provisioned = await _provision(client)
    token = provisioned["invite_url"].split("token=")[1]

    client.cookies.clear()
    resp = await client.post(
        "/api/v1/auth/accept-invite", json={"token": token, "password": "chosen-pass-1"}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["user"]["email"] == NEW["email"]
    # Signed in already — no second trip through the login form.
    assert (await client.get("/api/v1/auth/me")).status_code == 200


@pytest.mark.asyncio
async def test_an_invite_works_only_once(client):
    await _seed_admin()
    await _login_admin(client)
    token = (await _provision(client))["invite_url"].split("token=")[1]

    first = await client.post(
        "/api/v1/auth/accept-invite", json={"token": token, "password": "chosen-pass-1"}
    )
    assert first.status_code == 200
    second = await client.post(
        "/api/v1/auth/accept-invite", json={"token": token, "password": "other-pass-99"}
    )
    assert second.status_code == 401


@pytest.mark.asyncio
async def test_a_bad_token_is_refused_with_the_same_message(client):
    """Unknown, expired and used must not be distinguishable."""
    await _seed_admin()
    await _login_admin(client)
    await _provision(client)

    resp = await client.post(
        "/api/v1/auth/accept-invite", json={"token": "not-a-real-token", "password": "abcdefgh1"}
    )
    assert resp.status_code == 401
    assert "invalid or has expired" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_the_plaintext_token_is_never_stored(client):
    """Only the hash is persisted — a readable column is a list of working
    credentials."""
    import sqlalchemy as sa

    await _seed_admin()
    await _login_admin(client)
    token = (await _provision(client))["invite_url"].split("token=")[1]

    async with SessionFactory() as session:
        rows = (await session.execute(sa.text("SELECT token_hash FROM invite_tokens"))).all()
    assert rows and all(token not in row[0] for row in rows)


@pytest.mark.asyncio
async def test_provisioning_a_duplicate_email_is_a_conflict(client):
    await _seed_admin()
    await _login_admin(client)
    await _provision(client)
    resp = await client.post("/api/v1/admin/users", json=NEW)
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_only_an_admin_can_provision(client):
    resp = await client.post("/api/v1/admin/users", json=NEW)
    assert resp.status_code == 401
