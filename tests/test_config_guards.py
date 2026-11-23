"""The settings this API refuses to start with.

A boot crash is loud and immediate. The alternative, every time, is a service
that reports itself perfectly healthy while doing something silently wrong —
signing sessions with a key published in the repo, taking payments it cannot
confirm, or handing out links to an address nobody can reach.

The validator these cover had no tests at all, which is a poor state for the
code whose whole job is to stop a bad deploy.
"""

import pytest

from app.core.config import Settings

#: Enough to get past the other guards, so each test fails for its own reason.
#:
#: `cookie_secure` is here because `conftest` exports COOKIE_SECURE=false for
#: the test client, pydantic-settings reads the environment, and a separate
#: guard refuses that outside local — which would make every test below fail
#: for a reason none of them is about.
SOUND = dict(
    environment="production",
    jwt_secret_key="b7f3" * 10,
    media_backend="r2",
    public_base_url="https://cabmoramedia.com",
    cookie_secure=True,
)


def test_a_sound_production_configuration_starts():
    """The control. Without it, a guard that refused everything would pass
    every other test here."""
    assert Settings(**SOUND).public_base_url == "https://cabmoramedia.com"


@pytest.mark.parametrize(
    "url",
    ["", "http://localhost:5173", "https://localhost:5173", "http://cabmoramedia.com"],
)
def test_a_public_base_url_nobody_can_reach_is_refused(url):
    """Share links, invite links and the `og:image` a messaging app fetches
    are all built on this one value.

    Left on the shipped default the API is healthy and every link it hands
    out points at somebody's laptop — which presents as "the WhatsApp preview
    is broken" rather than as a missing variable, and cost a UAT round
    saying so.
    """
    with pytest.raises(ValueError, match="PUBLIC_BASE_URL"):
        Settings(**{**SOUND, "public_base_url": url})


def test_local_development_is_left_alone():
    """The guards must not make a laptop unusable.

    Every one of them is about a deployed environment, and a developer
    running the stack has localhost in exactly the place production must not.
    """
    local = Settings(
        environment="local",
        public_base_url="http://localhost:5173",
        cookie_secure=False,
    )
    assert local.public_base_url == "http://localhost:5173"


def test_the_shipped_jwt_secret_is_refused_in_production():
    from app.core.config import DEFAULT_SECRET

    with pytest.raises(ValueError, match="JWT_SECRET_KEY"):
        Settings(**{**SOUND, "jwt_secret_key": DEFAULT_SECRET})


def test_serving_media_through_the_container_is_refused_in_production():
    with pytest.raises(ValueError, match="MEDIA_BACKEND"):
        Settings(**{**SOUND, "media_backend": "local"})


def test_a_live_stripe_key_on_a_laptop_is_refused():
    """The one guard on the local side of the early return: the gateway is
    chosen by whether keys are present rather than by the environment name,
    so a live key in a local .env would charge real cards."""
    with pytest.raises(ValueError, match="STRIPE_SECRET_KEY"):
        Settings(
            environment="local",
            stripe_secret_key="sk_live_abc123",
            cookie_secure=False,
        )
