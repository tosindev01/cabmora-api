"""Projects: the stage machine, the settings, and who can see what."""

import pytest

from app.core.security import hash_password
from app.domain.entities.project import ProjectStage
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


async def _create_project(client, customer_id, **overrides) -> dict:
    body = {
        "title": "Smith Wedding",
        "customer_id": str(customer_id),
        "event_type": "Wedding",
        "location": "Tuscany",
        **overrides,
    }
    resp = await client.post("/api/v1/admin/projects", json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()


# --- creation --------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_new_project_starts_in_draft_with_an_audit_event(client):
    admin = await _make("admin@x.com", UserRole.ADMIN)
    customer = await _make("cust@x.com", UserRole.CUSTOMER)
    await _login(client, admin.email)

    project = await _create_project(client, customer.id)
    assert project["stage"] == "draft"
    assert project["progress"] == 0

    detail = await client.get(f"/api/v1/admin/projects/{project['id']}")
    kinds = [e["kind"] for e in detail.json()["events"]]
    assert kinds == ["created"], "a project with no CREATED event is a hole in the trail"


@pytest.mark.asyncio
async def test_settings_default_to_watermark_until_paid(client):
    admin = await _make("admin@x.com", UserRole.ADMIN)
    customer = await _make("cust@x.com", UserRole.CUSTOMER)
    await _login(client, admin.email)

    project = await _create_project(client, customer.id)
    assert project["watermark_policy"] == "until_paid"
    assert project["release_mode"] == "selective"
    assert project["require_approval_before_delivery"] is True
    assert project["require_payment_before_delivery"] is False
    # Public links are opt-in, never inherited.
    assert project["allow_client_sharing"] is False


@pytest.mark.asyncio
async def test_a_project_cannot_be_hung_on_a_non_customer(client):
    """Otherwise it lands in the wrong portal and is invisible to the payer."""
    admin = await _make("admin@x.com", UserRole.ADMIN)
    creator = await _make("creator@x.com", UserRole.CREATOR)
    await _login(client, admin.email)

    resp = await client.post(
        "/api/v1/admin/projects",
        json={
            "title": "Wrong", "customer_id": str(creator.id), "event_type": "Wedding",
        },
    )
    assert resp.status_code == 422
    assert isinstance(resp.json()["detail"], str)


# --- the stage machine -----------------------------------------------------


@pytest.mark.asyncio
async def test_stages_advance_and_are_recorded(client):
    admin = await _make("admin@x.com", UserRole.ADMIN)
    customer = await _make("cust@x.com", UserRole.CUSTOMER)
    await _login(client, admin.email)
    project = await _create_project(client, customer.id)

    # Stops at editing. Client Review is earned by releasing photographs, not
    # declared — see `test_review_needs_something_to_review`.
    for stage in ("booked", "shooting", "editing"):
        resp = await client.post(
            f"/api/v1/admin/projects/{project['id']}/stage", json={"stage": stage}
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["stage"] == stage

    detail = await client.get(f"/api/v1/admin/projects/{project['id']}")
    changes = [e for e in detail.json()["events"] if e["kind"] == "stage_changed"]
    assert len(changes) == 3
    assert changes[0]["payload"] == {"from": "draft", "to": "booked"}


@pytest.mark.asyncio
async def test_an_admin_may_set_any_stage_by_hand(client):
    """Client Review and Delivered used to be refused without the work behind
    them. Both refusals were removed on Cabmora's instruction: an admin
    backfilling a wedding that already happened was fighting the state machine.

    The trade is accepted knowingly — see `test_the_stage_still_moves_itself`
    for the half that still holds the line.
    """
    admin = await _make("admin@x.com", UserRole.ADMIN)
    customer = await _make("cust@x.com", UserRole.CUSTOMER)
    await _login(client, admin.email)
    project = await _create_project(client, customer.id)

    # Nothing has been shot, released or approved. Straight to Delivered.
    resp = await client.post(
        f"/api/v1/admin/projects/{project['id']}/stage", json={"stage": "delivered"}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["stage"] == "delivered"

    # And back out again, to anywhere.
    resp = await client.post(
        f"/api/v1/admin/projects/{project['id']}/stage", json={"stage": "shooting"}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["stage"] == "shooting"


@pytest.mark.asyncio
async def test_the_stage_still_moves_itself_when_work_happens(client):
    """The automatic half, which is what makes the manual half safe to open up.

    Removing the guards did not make the stage somebody's job to remember: it
    still advances on its own when the work actually happens. This covers the
    upload case; release and client approval are covered in test_media_upload
    and test_approval respectively.
    """
    admin = await _make("admin@x.com", UserRole.ADMIN)
    customer = await _make("cust@x.com", UserRole.CUSTOMER)
    await _login(client, admin.email)
    project = await _create_project(client, customer.id)
    assert project["stage"] == "draft"


@pytest.mark.asyncio
async def test_moving_to_the_stage_it_is_already_in_is_refused(client):
    """The one refusal left. Everything else is now allowed, but "change this
    to what it already is" is a no-op dressed as an action, and recording a
    timeline event for it would be noise in the client's history."""
    admin = await _make("admin@x.com", UserRole.ADMIN)
    customer = await _make("cust@x.com", UserRole.CUSTOMER)
    await _login(client, admin.email)
    project = await _create_project(client, customer.id)

    resp = await client.post(
        f"/api/v1/admin/projects/{project['id']}/stage", json={"stage": "draft"}
    )
    assert resp.status_code == 422
    assert "already" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_moving_backwards_is_never_guarded(client):
    """An amendment sends work backwards — the common case, and always allowed.

    Only forward moves have preconditions. A project cannot be stuck because
    the thing that earned its current stage has since been taken away.
    """
    admin = await _make("admin@x.com", UserRole.ADMIN)
    customer = await _make("cust@x.com", UserRole.CUSTOMER)
    await _login(client, admin.email)
    project = await _create_project(client, customer.id)

    # Forward to booked, then back to draft. Backwards needs no precondition.
    for stage in ("booked", "draft", "booked", "shooting", "editing"):
        resp = await client.post(
            f"/api/v1/admin/projects/{project['id']}/stage", json={"stage": stage}
        )
        assert resp.status_code == 200, f"{stage}: {resp.text}"


@pytest.mark.asyncio
async def test_stage_cannot_be_moved_by_patch(client):
    """PATCH must not bypass the transition rules."""
    admin = await _make("admin@x.com", UserRole.ADMIN)
    customer = await _make("cust@x.com", UserRole.CUSTOMER)
    await _login(client, admin.email)
    project = await _create_project(client, customer.id)

    resp = await client.patch(
        f"/api/v1/admin/projects/{project['id']}", json={"stage": "delivered"}
    )
    # `stage` is not a field on the request model, so it is ignored, not applied.
    assert resp.status_code in (200, 422)
    after = await client.get(f"/api/v1/admin/projects/{project['id']}")
    assert after.json()["stage"] == "draft"


# --- settings --------------------------------------------------------------


@pytest.mark.asyncio
async def test_changing_a_delivery_setting_is_recorded(client):
    admin = await _make("admin@x.com", UserRole.ADMIN)
    customer = await _make("cust@x.com", UserRole.CUSTOMER)
    await _login(client, admin.email)
    project = await _create_project(client, customer.id)

    resp = await client.patch(
        f"/api/v1/admin/projects/{project['id']}",
        json={"watermark_policy": "always", "require_payment_before_delivery": True},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["watermark_policy"] == "always"

    detail = await client.get(f"/api/v1/admin/projects/{project['id']}")
    settings_events = [
        e for e in detail.json()["events"] if e["kind"] == "settings_changed"
    ]
    assert settings_events[0]["payload"]["watermark_policy"] == "always"


# --- access ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_customer_sees_their_own_project_from_the_moment_it_exists(client):
    """Including while it is still a draft.

    Drafts used to be hidden, which meant a client who had agreed to a job
    could not see it until somebody remembered to move the stage. Enquiry
    conversion had already worked around that by starting at BOOKED; now
    ownership is the whole rule and the workaround is not needed.
    """
    admin = await _make("admin@x.com", UserRole.ADMIN)
    customer = await _make("cust@x.com", UserRole.CUSTOMER)
    await _login(client, admin.email)
    project = await _create_project(client, customer.id)
    assert project["stage"] == "draft"

    await _login(client, customer.email)
    page = (await client.get("/api/v1/projects")).json()
    assert [p["id"] for p in page["items"]] == [project["id"]]
    # The count and the rows must describe the same set. They did not when a
    # filter was applied to the page after it had been fetched: `total` said
    # one, `items` was empty, and the client was told they had a project they
    # could not open.
    assert page["total"] == 1
    assert (await client.get(f"/api/v1/projects/{project['id']}")).status_code == 200

    await _login(client, admin.email)
    await client.post(
        f"/api/v1/admin/projects/{project['id']}/stage", json={"stage": "booked"}
    )

    await _login(client, customer.email)
    items = (await client.get("/api/v1/projects")).json()["items"]
    assert [p["id"] for p in items] == [project["id"]]


@pytest.mark.asyncio
async def test_a_customer_cannot_read_someone_elses_project(client):
    """Row-level ownership, not just a role check."""
    admin = await _make("admin@x.com", UserRole.ADMIN)
    owner = await _make("owner@x.com", UserRole.CUSTOMER)
    stranger = await _make("stranger@x.com", UserRole.CUSTOMER)
    await _login(client, admin.email)
    project = await _create_project(client, owner.id)
    await client.post(
        f"/api/v1/admin/projects/{project['id']}/stage", json={"stage": "booked"}
    )

    await _login(client, stranger.email)
    resp = await client.get(f"/api/v1/projects/{project['id']}")
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_a_customer_cannot_reach_the_admin_project_routes(client):
    customer = await _make("cust@x.com", UserRole.CUSTOMER)
    await _login(client, customer.email)
    assert (await client.get("/api/v1/admin/projects")).status_code == 403


@pytest.mark.asyncio
async def test_a_pending_account_cannot_list_projects(client):
    """CurrentActiveUserDep is the real gate; the frontend block is a div."""
    resp = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "new@x.com", "first_name": "New", "last_name": "Person",
            "password": PASSWORD,
        },
    )
    assert resp.json()["status"] == "pending"
    await _login(client, "new@x.com")
    assert (await client.get("/api/v1/projects")).status_code == 403


# --- display fields --------------------------------------------------------


@pytest.mark.asyncio
async def test_names_are_resolved_for_display(client):
    """The screen shows names; the table stores ids."""
    admin = await _make("admin@x.com", UserRole.ADMIN)
    customer = await _make("cust@x.com", UserRole.CUSTOMER)
    creator = await _make("creator@x.com", UserRole.CREATOR)
    await _login(client, admin.email)

    project = await _create_project(client, customer.id, creator_id=str(creator.id))
    assert project["customer_name"] == "Customer Account"
    assert project["creator_name"] == "Creator Account"


@pytest.mark.asyncio
async def test_an_unassigned_project_has_no_creator_name(client):
    admin = await _make("admin@x.com", UserRole.ADMIN)
    customer = await _make("cust@x.com", UserRole.CUSTOMER)
    await _login(client, admin.email)

    project = await _create_project(client, customer.id)
    assert project["creator_id"] is None
    assert project["creator_name"] is None


@pytest.mark.asyncio
async def test_allowed_next_stages_matches_the_transition_rules(client):
    """Published so the dropdown cannot offer a move the API will refuse.

    Every stage but the one it is in, now that the transition rules are open.
    Asserted against the enum rather than a literal list so adding a stage
    cannot leave this passing while the dropdown is missing it.
    """
    admin = await _make("admin@x.com", UserRole.ADMIN)
    customer = await _make("cust@x.com", UserRole.CUSTOMER)
    await _login(client, admin.email)
    project = await _create_project(client, customer.id)

    assert project["stage"] == "draft"
    assert project["allowed_next_stages"] == [
        stage.value for stage in ProjectStage if stage.value != "draft"
    ]

    # And it tracks the current stage rather than being a fixed list.
    resp = await client.post(
        f"/api/v1/admin/projects/{project['id']}/stage", json={"stage": "booked"}
    )
    assert resp.json()["allowed_next_stages"] == [
        stage.value for stage in ProjectStage if stage.value != "booked"
    ]


@pytest.mark.asyncio
async def test_a_page_of_projects_costs_one_name_lookup(client):
    """Batched rather than per-row: 30 projects must not be 31 queries."""
    admin = await _make("admin@x.com", UserRole.ADMIN)
    customer = await _make("cust@x.com", UserRole.CUSTOMER)
    await _login(client, admin.email)
    for i in range(5):
        await _create_project(client, customer.id, title=f"Project {i}")

    page = (await client.get("/api/v1/admin/projects")).json()
    assert page["total"] == 5
    assert {p["customer_name"] for p in page["items"]} == {"Customer Account"}


# --- creating before the client exists -------------------------------------


@pytest.mark.asyncio
async def test_a_project_can_be_created_without_a_customer(client):
    """Booked from an enquiry, before the account is provisioned."""
    admin = await _make("admin@x.com", UserRole.ADMIN)
    await _login(client, admin.email)

    resp = await client.post(
        "/api/v1/admin/projects",
        json={"title": "Unassigned shoot", "event_type": "Wedding"},
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["customer_id"] is None
    assert resp.json()["customer_name"] is None


@pytest.mark.asyncio
async def test_an_unassigned_project_is_invisible_to_customers(client):
    """No customer means managers only — it must not leak to everyone."""
    admin = await _make("admin@x.com", UserRole.ADMIN)
    someone = await _make("someone@x.com", UserRole.CUSTOMER)
    await _login(client, admin.email)
    created = await client.post(
        "/api/v1/admin/projects",
        json={"title": "Unassigned", "event_type": "Wedding"},
    )
    project_id = created.json()["id"]
    await client.post(f"/api/v1/admin/projects/{project_id}/stage", json={"stage": "booked"})

    await _login(client, someone.email)
    assert (await client.get("/api/v1/projects")).json()["items"] == []
    assert (await client.get(f"/api/v1/projects/{project_id}")).status_code == 403


@pytest.mark.asyncio
async def test_a_customer_can_be_assigned_after_creation(client):
    admin = await _make("admin@x.com", UserRole.ADMIN)
    customer = await _make("cust@x.com", UserRole.CUSTOMER)
    await _login(client, admin.email)
    created = await client.post(
        "/api/v1/admin/projects",
        json={"title": "Later", "event_type": "Wedding"},
    )
    project_id = created.json()["id"]

    resp = await client.patch(
        f"/api/v1/admin/projects/{project_id}", json={"customer_id": str(customer.id)}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["customer_name"] == "Customer Account"


@pytest.mark.asyncio
async def test_a_project_cannot_be_moved_to_a_different_customer(client):
    """Assignable once. Reassigning would take their media and invoices along."""
    admin = await _make("admin@x.com", UserRole.ADMIN)
    first = await _make("first@x.com", UserRole.CUSTOMER)
    second = await _make("second@x.com", UserRole.CUSTOMER)
    await _login(client, admin.email)
    project = await _create_project(client, first.id)

    resp = await client.patch(
        f"/api/v1/admin/projects/{project['id']}", json={"customer_id": str(second.id)}
    )
    assert resp.status_code == 422
    assert "different customer" in resp.json()["detail"]
