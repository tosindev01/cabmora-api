"""Authorisation: who may reach which section, and how that answer is built.

The one part of this system where a bug is silent. A broken gallery is
obvious the moment somebody looks at it; a coordinator who can read every
client's invoices looks exactly like a coordinator who cannot, right up until
it matters.

So these test the *rules*, not the screens: the union that decides what an
account can reach, the guards that refuse a request, the row-level checks
underneath them, and the four refusals that stop the mechanism being used to
escalate out of itself.
"""

import pytest

from app.core.security import hash_password
from app.domain.entities.access_group import AccessGroup
from app.domain.entities.user import (
    COORDINATOR_BASELINE,
    GRANTABLE,
    Permission,
    User,
    UserRole,
)
from app.infrastructure.database import SessionFactory
from app.infrastructure.repositories.access_group_repository_impl import (
    SqlAlchemyAccessGroupRepository,
)
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


async def _grant(client, user_id, permissions: list[str]) -> None:
    resp = await client.put(
        f"/api/v1/admin/users/{user_id}/permissions",
        json={"permissions": permissions},
    )
    assert resp.status_code == 200, resp.text


# ── the union ───────────────────────────────────────────────────────────
# `can()` is read by every guard, so these are the cheapest tests in the
# suite and the ones protecting the most.


def _user(role: UserRole, **kwargs) -> User:
    return User(
        email="x@y.com", first_name="A", last_name="B", hashed_password=None,
        role=role, **kwargs,
    )


def test_an_admin_reaches_everything():
    admin = _user(UserRole.ADMIN)
    assert all(admin.can(p) for p in Permission)


def test_a_coordinator_starts_with_the_baseline_and_nothing_else():
    devon = _user(UserRole.COORDINATOR)
    assert devon.can(Permission.PROJECTS)
    assert devon.can(Permission.ENQUIRIES)
    assert not devon.can(Permission.PAYMENTS)
    assert not devon.can(Permission.USERS)


def test_a_direct_grant_adds_to_the_baseline():
    devon = _user(UserRole.COORDINATOR, granted={Permission.PAYMENTS})
    assert devon.can(Permission.PAYMENTS)
    # Additive, never subtractive: the baseline survives a grant.
    assert all(devon.can(p) for p in COORDINATOR_BASELINE)


def test_a_group_adds_the_same_way():
    devon = _user(UserRole.COORDINATOR, from_groups={Permission.REVIEWS})
    assert devon.can(Permission.REVIEWS)


def test_both_sources_union_rather_than_override():
    devon = _user(
        UserRole.COORDINATOR,
        granted={Permission.PAYMENTS},
        from_groups={Permission.REVIEWS},
    )
    assert devon.can(Permission.PAYMENTS)
    assert devon.can(Permission.REVIEWS)


def test_a_customer_is_refused_even_holding_a_permission_row():
    """Console permissions mean nothing outside the console.

    A row can exist — somebody was a coordinator and was demoted — and it
    must grant nothing, because the role check happens first.
    """
    client = _user(UserRole.CUSTOMER, granted={Permission.PAYMENTS})
    assert not client.can(Permission.PAYMENTS)


def test_a_creator_is_refused_the_same_way():
    creator = _user(UserRole.CREATOR, from_groups={Permission.PAYMENTS})
    assert not creator.can(Permission.PAYMENTS)


# ── the guards ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_coordinator_without_the_grant_is_refused_the_section(client):
    await _make("admin@x.com", UserRole.ADMIN)
    devon = await _make("devon@x.com", UserRole.COORDINATOR)
    await _login(client, devon.email)

    assert (await client.get("/api/v1/admin/reviews")).status_code == 403
    assert (await client.get("/api/v1/admin/invoices")).status_code == 403
    assert (await client.get("/api/v1/admin/reports/monthly")).status_code == 403


@pytest.mark.asyncio
async def test_a_grant_opens_exactly_the_section_granted(client):
    admin = await _make("admin@x.com", UserRole.ADMIN)
    devon = await _make("devon@x.com", UserRole.COORDINATOR)
    await _login(client, admin.email)
    await _grant(client, devon.id, ["reviews"])

    await _login(client, devon.email)
    assert (await client.get("/api/v1/admin/reviews")).status_code == 200
    # And nothing else moved.
    assert (await client.get("/api/v1/admin/invoices")).status_code == 403


@pytest.mark.asyncio
async def test_the_three_withheld_sections_stay_admin_only(client):
    """Users, Team and Settings are not grantable, and the API says so.

    Each is an escalation rather than a convenience: user management is a
    promotion, team membership reaches every client's photographs.
    """
    admin = await _make("admin@x.com", UserRole.ADMIN)
    devon = await _make("devon@x.com", UserRole.COORDINATOR)
    await _login(client, admin.email)

    for permission in ("users", "team", "settings"):
        resp = await client.put(
            f"/api/v1/admin/users/{devon.id}/permissions",
            json={"permissions": [permission]},
        )
        assert resp.status_code == 422, permission
        assert permission in resp.json()["detail"]

    await _login(client, devon.email)
    assert (await client.get("/api/v1/admin/users")).status_code == 403


@pytest.mark.asyncio
async def test_a_coordinator_cannot_grant_anything(client):
    await _make("admin@x.com", UserRole.ADMIN)
    devon = await _make("devon@x.com", UserRole.COORDINATOR)
    other = await _make("other@x.com", UserRole.COORDINATOR)
    await _login(client, devon.email)

    resp = await client.put(
        f"/api/v1/admin/users/{other.id}/permissions", json={"permissions": ["reviews"]}
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_nobody_edits_their_own_access(client):
    admin = await _make("admin@x.com", UserRole.ADMIN)
    await _login(client, admin.email)

    resp = await client.put(
        f"/api/v1/admin/users/{admin.id}/permissions", json={"permissions": ["reviews"]}
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_a_customer_cannot_be_granted_a_section(client):
    admin = await _make("admin@x.com", UserRole.ADMIN)
    customer = await _make("cust@x.com", UserRole.CUSTOMER)
    await _login(client, admin.email)

    resp = await client.put(
        f"/api/v1/admin/users/{customer.id}/permissions",
        json={"permissions": ["reviews"]},
    )
    assert resp.status_code == 422


# ── groups ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_group_grants_through_to_the_guard(client):
    """The whole point, end to end: membership reaches the door."""
    admin = await _make("admin@x.com", UserRole.ADMIN)
    devon = await _make("devon@x.com", UserRole.COORDINATOR)
    await _login(client, admin.email)

    group = (
        await client.post(
            "/api/v1/admin/groups",
            json={"name": "Billing cover", "permissions": ["payments"]},
        )
    ).json()
    resp = await client.put(
        f"/api/v1/admin/users/{devon.id}/groups", json={"group_ids": [group["id"]]}
    )
    assert resp.status_code == 200
    assert resp.json()["from_groups"] == ["payments"]

    await _login(client, devon.email)
    assert (await client.get("/api/v1/admin/invoices")).status_code == 200


@pytest.mark.asyncio
async def test_deleting_a_group_takes_back_what_it_gave(client):
    admin = await _make("admin@x.com", UserRole.ADMIN)
    devon = await _make("devon@x.com", UserRole.COORDINATOR)
    await _login(client, admin.email)

    group = (
        await client.post(
            "/api/v1/admin/groups",
            json={"name": "Billing cover", "permissions": ["payments"]},
        )
    ).json()
    await client.put(
        f"/api/v1/admin/users/{devon.id}/groups", json={"group_ids": [group["id"]]}
    )
    assert (await client.delete(f"/api/v1/admin/groups/{group['id']}")).status_code == 204

    await _login(client, devon.email)
    assert (await client.get("/api/v1/admin/invoices")).status_code == 403


@pytest.mark.asyncio
async def test_a_group_cannot_carry_a_withheld_section(client):
    """Otherwise the group is the ladder the per-user rules were built to stop."""
    admin = await _make("admin@x.com", UserRole.ADMIN)
    await _login(client, admin.email)

    resp = await client.post(
        "/api/v1/admin/groups", json={"name": "Super", "permissions": ["users"]}
    )
    assert resp.status_code == 422
    assert "users" in resp.json()["detail"]


def test_the_entity_refuses_a_withheld_section_too():
    """Checked on the entity, so a second caller cannot route around it."""
    with pytest.raises(Exception):
        AccessGroup(name="Super", permissions={Permission.USERS})
    assert Permission.USERS not in GRANTABLE


@pytest.mark.asyncio
async def test_a_group_counts_its_members(client):
    admin = await _make("admin@x.com", UserRole.ADMIN)
    devon = await _make("devon@x.com", UserRole.COORDINATOR)
    await _login(client, admin.email)

    group = (
        await client.post(
            "/api/v1/admin/groups", json={"name": "Cover", "permissions": []}
        )
    ).json()
    assert group["member_count"] == 0

    await client.put(
        f"/api/v1/admin/users/{devon.id}/groups", json={"group_ids": [group["id"]]}
    )
    listed = (await client.get("/api/v1/admin/groups")).json()
    assert listed[0]["member_count"] == 1


@pytest.mark.asyncio
async def test_only_coordinators_go_in_groups(client):
    admin = await _make("admin@x.com", UserRole.ADMIN)
    customer = await _make("cust@x.com", UserRole.CUSTOMER)
    await _login(client, admin.email)

    group = (
        await client.post(
            "/api/v1/admin/groups", json={"name": "Cover", "permissions": []}
        )
    ).json()
    resp = await client.put(
        f"/api/v1/admin/users/{customer.id}/groups", json={"group_ids": [group["id"]]}
    )
    assert resp.status_code == 422


# ── the row-level checks underneath the guards ──────────────────────────


@pytest.mark.asyncio
async def test_the_grant_reaches_past_the_door_into_the_rows(client):
    """A guard that admits somebody has said nothing about what they may do.

    Billing's own checks refused a granted coordinator until they were taught
    about permissions — which would have meant a grant that opened a screen
    where every action failed.
    """
    from app.application.use_cases.billing._access import (
        assert_may_bill_project,
        assert_may_confirm_money,
        assert_may_manage,
    )
    from app.core.exceptions import PermissionDeniedError

    plain = _user(UserRole.COORDINATOR)
    granted = _user(UserRole.COORDINATOR, granted={Permission.PAYMENTS})

    for actor, should_pass in ((plain, False), (granted, True)):
        try:
            assert_may_manage(actor, None, None)
            assert_may_bill_project(actor, None)
            assert_may_confirm_money(actor, "confirm a payment")
            passed = True
        except PermissionDeniedError:
            passed = False
        assert passed is should_pass


@pytest.mark.asyncio
async def test_a_hydrated_user_carries_both_sources(client):
    """The repository is what the guards actually see.

    A `User` loaded without its grants would answer `can()` wrongly and the
    guards would refuse somebody who has access — which is why every read
    hydrates, including the one behind the session.
    """
    admin = await _make("admin@x.com", UserRole.ADMIN)
    devon = await _make("devon@x.com", UserRole.COORDINATOR)
    await _login(client, admin.email)
    await _grant(client, devon.id, ["reviews"])

    group = (
        await client.post(
            "/api/v1/admin/groups",
            json={"name": "Billing cover", "permissions": ["payments"]},
        )
    ).json()
    await client.put(
        f"/api/v1/admin/users/{devon.id}/groups", json={"group_ids": [group["id"]]}
    )

    async with SessionFactory() as session:
        loaded = await SqlAlchemyUserRepository(session).get_by_id(devon.id)

    assert loaded is not None
    assert loaded.granted == {Permission.REVIEWS}
    assert loaded.from_groups == {Permission.PAYMENTS}
    assert loaded.group_names == ["Billing cover"]
    assert loaded.can(Permission.REVIEWS) and loaded.can(Permission.PAYMENTS)
    assert not loaded.can(Permission.USERS)


@pytest.mark.asyncio
async def test_group_repository_cleans_up_after_itself(client):
    """A membership pointing at a deleted group grants nothing but looks like
    it grants something, so it goes with the group."""
    devon = await _make("devon@x.com", UserRole.COORDINATOR)
    async with SessionFactory() as session:
        groups = SqlAlchemyAccessGroupRepository(session)
        group = await groups.add(
            AccessGroup(name="Cover", permissions={Permission.REPORTS})
        )
        await groups.set_members(group.id, {devon.id})
        assert await groups.member_ids(group.id) == [devon.id]
        await groups.delete(group.id)
        assert await groups.get_by_id(group.id) is None
        assert await groups.member_ids(group.id) == []


# ── where a signed-in person is sent ─────────────────────────────────────
@pytest.mark.asyncio
async def test_staff_are_told_where_the_console_is(client, monkeypatch):
    """UAT #9: "team creation bug — log in access redirect to customer page
    instead of admin".

    A new coordinator accepting an invite signs in at the address they know,
    which is the public site. The console is a separate application on its own
    origin, so the public site cannot route there — it has to be told, and the
    API is the only part that knows the address.

    Before this, `homePathForRole` sent an admin to the *Creator Studio*
    dashboard and a coordinator to the marketing homepage, and a comment
    explained that as deliberate.
    """
    from app.core.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "admin_base_url", "https://console.example.com")

    for role in (UserRole.ADMIN, UserRole.COORDINATOR):
        user = await _make(f"console-{role.value}@example.com", role)
        await _login(client, user.email)
        me = (await client.get("/api/v1/auth/me")).json()
        assert me["console_url"] == "https://console.example.com", role


@pytest.mark.asyncio
async def test_a_customer_is_never_handed_the_console_address(client, monkeypatch):
    """A customer has no business being sent there, so they are not told where
    it is — the field is absent for them whatever the setting says."""
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "admin_base_url", "https://console.example.com")

    for role in (UserRole.CUSTOMER, UserRole.CREATOR):
        user = await _make(f"noconsole-{role.value}@example.com", role)
        await _login(client, user.email)
        assert (await client.get("/api/v1/auth/me")).json()["console_url"] is None


@pytest.mark.asyncio
async def test_an_unset_console_url_is_null_rather_than_a_guess(client, monkeypatch):
    """Null, so the caller leaves them where they are. A redirect to an invented
    origin is a 404 with no way back."""
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "admin_base_url", None)

    user = await _make("noconfig@example.com", UserRole.ADMIN)
    await _login(client, user.email)
    assert (await client.get("/api/v1/auth/me")).json()["console_url"] is None
