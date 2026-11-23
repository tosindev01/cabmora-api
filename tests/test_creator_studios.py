from datetime import datetime, timezone

import pytest
from httpx import AsyncClient

from app.core.security import hash_password
from app.domain.entities.user import UserRole, UserStatus
from app.infrastructure.database import SessionFactory
from app.infrastructure.models.user import UserModel


async def _create_user_and_login(
    client: AsyncClient,
    *,
    email: str,
    role: UserRole = UserRole.CREATOR,
    first_name: str = "Sarah",
    last_name: str = "Cabmora",
) -> str:
    async with SessionFactory() as session:
        session.add(
            UserModel(
                id=__import__("uuid").uuid4().__str__(),
                email=email,
                first_name=first_name,
                last_name=last_name,
                hashed_password=hash_password("StrongPass123!"),
                role=role.value,
                status=UserStatus.ACTIVE.value,
                created_at=datetime.now(timezone.utc),
            )
        )
        await session.commit()

    res = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "StrongPass123!"},
    )
    assert res.status_code == 200, res.text
    return res.json()["access_token"]


@pytest.mark.asyncio
async def test_creator_studio_landing_page_and_bookings_flow(client: AsyncClient):
    token = await _create_user_and_login(client, email="creator1@cabmora.com")
    headers = {"Authorization": f"Bearer {token}"}

    # 1. Initial GET returns default derived studio profile
    r0 = await client.get("/api/v1/creators/me/profile", headers=headers)
    assert r0.status_code == 200, r0.text
    assert r0.json()["slug"] == "sarah-cabmora"

    # 2. Save full studio profile, custom landing_config & portfolio items
    payload = {
        "slug": "sarah-editorial",
        "is_published": True,
        "studio_name": "Sarah Editorial Studio",
        "legal_name": "Sarah Visuals Ltd",
        "specialization": "Editorial & Destination Cinema",
        "categories": ["Editorial", "4K Cinema"],
        "bio": "Bespoke visual storytelling.",
        "experience_years": 9,
        "team_size": "2 - 5 Creatives",
        "currency": "USD ($)",
        "day_rate": 3200,
        "tax_id": "US-12345",
        "cover_url": "https://images.unsplash.com/photo-1492691527719-9d1e07e534b4",
        "primary_email": "creator1@cabmora.com",
        "secondary_email": "bookings@saraheditorial.com",
        "phone": "+1 555 0100",
        "allow_sms_alerts": True,
        "address": "450 Fashion Ave",
        "city": "New York, NY",
        "country": "United States",
        "timezone": "UTC-05:00",
        "socials": {"instagram": "@sarah.editorial"},
        "landing_config": {
            "theme_preset": "forest-luxe",
            "accent_token": "gold",
            "heading_font": "serif",
            "hero_headline": "Timeless *Visual* Stories",
        },
        "portfolio_items": [
            {
                "title": "Milan Fashion Week",
                "subtitle": "AW26 Editorial",
                "category": "Editorial",
                "media_type": "photo",
                "media_url": "https://images.unsplash.com/photo-1509631179647-0177331693ae",
                "featured": True,
                "sort_order": 1,
                "gallery_images": [
                    "https://images.unsplash.com/photo-1509631179647-0177331693ae"
                ],
            }
        ],
    }
    r1 = await client.put("/api/v1/creators/me/profile", json=payload, headers=headers)
    assert r1.status_code == 200, r1.text
    saved = r1.json()
    assert saved["slug"] == "sarah-editorial"
    assert saved["landing_config"]["theme_preset"] == "forest-luxe"
    assert len(saved["portfolio_items"]) == 1

    # 3. Public endpoint fetches the page without auth
    pub = await client.get("/api/v1/creators/public/sarah-editorial")
    assert pub.status_code == 200, pub.text
    assert pub.json()["studio_name"] == "Sarah Editorial Studio"
    assert pub.json()["portfolio_items"][0]["title"] == "Milan Fashion Week"

    # 4. Another creator cannot claim the same slug
    token2 = await _create_user_and_login(
        client, email="creator2@cabmora.com", first_name="Alex", last_name="Vance"
    )
    dup = await client.put(
        "/api/v1/creators/me/profile",
        json=payload,
        headers={"Authorization": f"Bearer {token2}"},
    )
    assert dup.status_code == 409

    # 5. Public visitor submits a booking application
    bk = await client.post(
        "/api/v1/creators/public/sarah-editorial/bookings",
        json={
            "client_name": "Elena Rostova",
            "client_email": "elena@maisonverve.com",
            "service_title": "Commercial & Editorial Campaign",
            "event_type": "Editorial",
            "preferred_date": "2026-12-20",
            "location": "Paris, France",
            "budget_range": "$5,000 – $10,000",
            "project_brief": "Two-day campaign shoot for Resort collection.",
        },
    )
    assert bk.status_code == 201, bk.text
    booking_id = bk.json()["id"]
    assert bk.json()["status"] == "new"

    # 6. Creator lists and updates the booking status
    client.cookies.clear()
    listed = await client.get("/api/v1/creators/me/bookings", headers=headers)
    assert listed.status_code == 200
    assert len(listed.json()) == 1

    patched = await client.patch(
        f"/api/v1/creators/me/bookings/{booking_id}",
        json={"status": "booked"},
        headers=headers,
    )
    assert patched.status_code == 200
    assert patched.json()["status"] == "booked"
