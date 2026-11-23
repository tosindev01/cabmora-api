import pytest

REGISTER = {
    "email": "taiwo@example.com",
    "first_name": "Taiwo",
    "last_name": "K",
    "password": "password123",
}


@pytest.mark.asyncio
async def test_register_login_me_flow(client):
    resp = await client.post("/api/v1/auth/register", json=REGISTER)
    assert resp.status_code == 201, resp.text
    assert resp.json()["email"] == REGISTER["email"]
    assert resp.json()["role"] == "customer"

    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": REGISTER["email"], "password": REGISTER["password"]},
    )
    assert resp.status_code == 200, resp.text
    token = resp.json()["access_token"]

    # Drop the session cookie login just set, so this asserts the bearer path
    # rather than silently passing on the cookie.
    client.cookies.clear()
    resp = await client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 200
    assert resp.json()["email"] == REGISTER["email"]


@pytest.mark.asyncio
async def test_duplicate_email_conflict(client):
    await client.post("/api/v1/auth/register", json=REGISTER)
    resp = await client.post("/api/v1/auth/register", json=REGISTER)
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_wrong_password_unauthorized(client):
    await client.post("/api/v1/auth/register", json=REGISTER)
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": REGISTER["email"], "password": "wrong-password"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_me_requires_token(client):
    resp = await client.get("/api/v1/auth/me")
    assert resp.status_code == 401


COOKIE = "cabmora_session"


async def _register_and_login(client):
    await client.post("/api/v1/auth/register", json=REGISTER)
    return await client.post(
        "/api/v1/auth/login",
        json={"email": REGISTER["email"], "password": REGISTER["password"]},
    )


@pytest.mark.asyncio
async def test_login_sets_httponly_session_cookie(client):
    resp = await _register_and_login(client)
    assert resp.status_code == 200, resp.text

    raw = resp.headers["set-cookie"]
    assert COOKIE in raw
    # The whole point: script must not be able to read it.
    assert "HttpOnly" in raw
    assert "SameSite=lax" in raw.replace("samesite", "SameSite")
    assert client.cookies.get(COOKIE)


@pytest.mark.asyncio
async def test_cookie_alone_authenticates(client):
    """A browser sends no Authorization header — the cookie has to be enough."""
    await _register_and_login(client)

    resp = await client.get("/api/v1/auth/me")
    assert resp.status_code == 200, resp.text
    assert resp.json()["email"] == REGISTER["email"]


@pytest.mark.asyncio
async def test_logout_clears_the_session(client):
    await _register_and_login(client)
    assert (await client.get("/api/v1/auth/me")).status_code == 200

    resp = await client.post("/api/v1/auth/logout")
    assert resp.status_code == 204

    assert not client.cookies.get(COOKIE)
    assert (await client.get("/api/v1/auth/me")).status_code == 401


@pytest.mark.asyncio
async def test_logout_without_a_session_is_not_an_error(client):
    """Clearing a cookie you may not have is harmless — never a 401."""
    resp = await client.post("/api/v1/auth/logout")
    assert resp.status_code == 204


@pytest.mark.asyncio
async def test_both_schemes_are_published_in_openapi(client):
    """Non-browser clients need the bearer scheme to stay documented."""
    schemes = (await client.get("/openapi.json")).json()["components"]["securitySchemes"]
    assert any(s.get("in") == "cookie" and s.get("name") == COOKIE for s in schemes.values())
    assert any(s.get("scheme") == "bearer" for s in schemes.values())


@pytest.mark.asyncio
async def test_full_name_is_derived_from_the_parts(client):
    """The API stores the parts and composes the whole, so they cannot drift."""
    resp = await client.post("/api/v1/auth/register", json=REGISTER)
    assert resp.status_code == 201, resp.text

    body = resp.json()
    assert body["first_name"] == "Taiwo"
    assert body["last_name"] == "K"
    assert body["full_name"] == "Taiwo K"


@pytest.mark.asyncio
async def test_register_rejects_a_missing_name_part(client):
    """Both halves are required — a blank surname would render as a stray space."""
    resp = await client.post(
        "/api/v1/auth/register",
        json={"email": "x@example.com", "first_name": "X", "password": "password123"},
    )
    assert resp.status_code == 422
