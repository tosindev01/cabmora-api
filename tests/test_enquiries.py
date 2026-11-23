import pytest

ENQUIRY = {
    "first_name": "Jane", "last_name": "Doe",
    "email": "jane@example.com",
    "event_type": "wedding",
    "message": "Looking for full-day wedding coverage in September.",
}


@pytest.mark.asyncio
async def test_submit_enquiry_public(client):
    resp = await client.post("/api/v1/enquiries", json=ENQUIRY)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["status"] == "new"
    assert body["email"] == ENQUIRY["email"]


@pytest.mark.asyncio
async def test_list_enquiries_requires_admin(client):
    """The listing moved to /admin/enquiries when leads gained a pipeline;
    the guard moved with it and is still asserted here."""
    resp = await client.get("/api/v1/admin/enquiries")
    assert resp.status_code == 401

    # a normal customer must be forbidden
    await client.post(
        "/api/v1/auth/register",
        json={
            "email": "c@example.com",
            "first_name": "C",
            "last_name": "Ustomer",
            "password": "password123",
        },
    )
    login = await client.post(
        "/api/v1/auth/login", json={"email": "c@example.com", "password": "password123"}
    )
    token = login.json()["access_token"]
    resp = await client.get(
        "/api/v1/admin/enquiries", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 403
