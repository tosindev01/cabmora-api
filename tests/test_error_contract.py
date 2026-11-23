"""Every failure answers in the same shape.

`detail` is a human-readable string on every error the API can produce. That is
the whole contract: a client reading `detail` must never get a sentence from one
failure and a list of objects from another — which is what FastAPI does by
default, and what used to render raw pydantic output in a user-facing banner.
"""

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.main import app

REGISTER = {
    "email": "err@example.com",
    "first_name": "Err",
    "last_name": "Or",
    "password": "password123",
}


async def _assert_string_detail(resp, expected_status: int) -> None:
    assert resp.status_code == expected_status, resp.text
    body = resp.json()
    assert "detail" in body, body
    assert isinstance(body["detail"], str), f"detail was {type(body['detail'])}: {body}"
    assert body["detail"].strip(), "detail must not be blank"


@pytest.mark.asyncio
async def test_401_detail_is_a_string(client):
    await _assert_string_detail(await client.get("/api/v1/auth/me"), 401)


@pytest.mark.asyncio
async def test_403_detail_is_a_string(client):
    await client.post("/api/v1/auth/register", json=REGISTER)
    await client.post(
        "/api/v1/auth/login",
        json={"email": REGISTER["email"], "password": REGISTER["password"]},
    )
    await _assert_string_detail(await client.get("/api/v1/admin/users"), 403)


@pytest.mark.asyncio
async def test_409_detail_is_a_string(client):
    await client.post("/api/v1/auth/register", json=REGISTER)
    await _assert_string_detail(
        await client.post("/api/v1/auth/register", json=REGISTER), 409
    )


@pytest.mark.asyncio
async def test_422_schema_error_detail_is_a_string_not_a_list(client):
    """The regression that mattered: FastAPI's default puts a list here."""
    resp = await client.post(
        "/api/v1/auth/register", json={**REGISTER, "password": "short"}
    )
    await _assert_string_detail(resp, 422)
    assert "at least 8 characters" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_422_also_carries_per_field_errors(client):
    """`detail` is the summary; `errors` is what a form highlights."""
    resp = await client.post(
        "/api/v1/auth/register", json={**REGISTER, "password": "short"}
    )
    errors = resp.json()["errors"]
    assert errors == [
        {"field": "password", "message": errors[0]["message"]}
    ], errors
    # "body" is stripped — the caller needs the field, not the location.
    assert not errors[0]["field"].startswith("body")


@pytest.mark.asyncio
async def test_a_crash_answers_in_the_same_shape_without_leaking(client_allowing_crashes):
    """500s are the easiest place to leak a stack trace or a table name."""
    crashing = FastAPI()

    resp = await client_allowing_crashes.get("/api/v1/boom")
    await _assert_string_detail(resp, 500)
    body = resp.json()
    assert "Traceback" not in body["detail"]
    assert "boom" not in body["detail"].lower()
    assert crashing is not None  # keeps the import honest


@pytest.fixture
async def client_allowing_crashes():
    """httpx re-raises app exceptions by default, which would bypass the
    handler we are trying to assert on."""

    @app.get("/api/v1/boom")
    async def _boom():  # pragma: no cover - exists only to explode
        raise RuntimeError("boom: secret table name")

    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
