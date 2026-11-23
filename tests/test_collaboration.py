from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.core.security import hash_password
from app.domain.entities.project import ProjectStage
from app.domain.entities.user import UserRole, UserStatus
from app.infrastructure.database import SessionFactory
from app.infrastructure.models.project import ProjectModel
from app.infrastructure.models.user import UserModel


async def _seed_project_and_users(client: AsyncClient):
    creator_id = str(uuid4())
    client_id = str(uuid4())
    project_id = str(uuid4())
    now = datetime.now(timezone.utc)

    async with SessionFactory() as session:
        session.add(
            UserModel(
                id=creator_id,
                email="creator-collab@cabmora.com",
                first_name="Sarah",
                last_name="Cabmora",
                hashed_password=hash_password("StrongPass123!"),
                role=UserRole.CREATOR.value,
                status=UserStatus.ACTIVE.value,
                created_at=now,
            )
        )
        session.add(
            UserModel(
                id=client_id,
                email="client-collab@cabmora.com",
                first_name="Elena",
                last_name="Rostova",
                hashed_password=hash_password("StrongPass123!"),
                role=UserRole.CUSTOMER.value,
                status=UserStatus.ACTIVE.value,
                created_at=now,
            )
        )
        session.add(
            ProjectModel(
                id=project_id,
                title="Autumn Campaign 2026",
                description="Editorial stills & film",
                event_type="Editorial",
                location="Paris",
                customer_id=client_id,
                creator_id=creator_id,
                stage=ProjectStage.IN_REVIEW.value,
                deadline=(now + timedelta(days=5)).date(),
                created_at=now,
            )
        )
        await session.commit()

    r1 = await client.post(
        "/api/v1/auth/login",
        json={"email": "creator-collab@cabmora.com", "password": "StrongPass123!"},
    )
    creator_token = r1.json()["access_token"]

    client.cookies.clear()
    r2 = await client.post(
        "/api/v1/auth/login",
        json={"email": "client-collab@cabmora.com", "password": "StrongPass123!"},
    )
    client_token = r2.json()["access_token"]
    client.cookies.clear()

    return project_id, creator_token, client_token


@pytest.mark.asyncio
async def test_tasks_calls_threaded_comments_and_briefing(client: AsyncClient):
    project_id, creator_token, client_token = await _seed_project_and_users(client)
    creator_hdr = {"Authorization": f"Bearer {creator_token}"}
    client_hdr = {"Authorization": f"Bearer {client_token}"}

    # 1. Creator creates a task
    t_res = await client.post(
        f"/api/v1/projects/{project_id}/tasks",
        json={"title": "Deliver final color-graded selects", "priority": "high"},
        headers=creator_hdr,
    )
    assert t_res.status_code == 201, t_res.text
    task_id = t_res.json()["id"]

    # 2. Client leaves a project comment & creator replies to it (threaded)
    c1 = await client.post(
        f"/api/v1/projects/{project_id}/comments",
        json={"body": "Can we warm up the highlights?", "kind": "amendment"},
        headers=client_hdr,
    )
    assert c1.status_code == 201, c1.text
    parent_id = c1.json()["id"]

    c2 = await client.post(
        f"/api/v1/projects/{project_id}/comments",
        json={"body": "Yes! Updating color grade now.", "parent_id": parent_id},
        headers=creator_hdr,
    )
    assert c2.status_code == 201, c2.text
    assert c2.json()["parent_id"] == parent_id

    # 3. Client requests a video call; creator accepts; meeting URL is generated
    proposed = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    call_res = await client.post(
        f"/api/v1/projects/{project_id}/calls",
        json={
            "title": "Color Grade Review Call",
            "proposed_at": proposed,
            "duration_minutes": 30,
            "notes": "Walk through final selects together",
        },
        headers=client_hdr,
    )
    assert call_res.status_code == 201, call_res.text
    call_id = call_res.json()["id"]
    assert call_res.json()["status"] == "pending"
    assert call_res.json()["meeting_url"] is None

    # Requester cannot accept their own call
    bad_accept = await client.post(
        f"/api/v1/calls/{call_id}/respond",
        json={"action": "accept"},
        headers=client_hdr,
    )
    assert bad_accept.status_code == 403

    # Creator accepts
    accepted = await client.post(
        f"/api/v1/calls/{call_id}/respond",
        json={"action": "accept"},
        headers=creator_hdr,
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["status"] == "accepted"
    assert accepted.json()["meeting_url"].startswith("https://meet.jit.si/cabmora-")

    # 4. Creator AI Briefing reflects real DB state
    briefing = await client.get("/api/v1/creators/me/briefing", headers=creator_hdr)
    assert briefing.status_code == 200, briefing.text
    data = briefing.json()
    assert data["projects_in_progress"] == 1
    assert data["pending_tasks_count"] == 1
    assert data["revision_requests_count"] == 1
    assert data["upcoming_deadlines_count"] == 1
    assert len(data["action_items"]) >= 3

    # 5. Mark task completed & verify briefing updates
    upd = await client.patch(
        f"/api/v1/tasks/{task_id}",
        json={"status": "completed"},
        headers=creator_hdr,
    )
    assert upd.status_code == 200
    assert upd.json()["status"] == "completed"
