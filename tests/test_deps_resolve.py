"""Every dependency provider must be definable on the Python production runs.

This exists because of a real outage. `deps.py` had a provider annotated with
`ProjectRepoDep` eighty lines before that alias was defined. Local Python 3.14
defers annotation evaluation (PEP 649) so nothing complained; the Dockerfile
pins 3.12, which evaluates annotations when the function is defined — and the
API and the cron both died on import with `NameError`, taking the contact form
down with them.

Every test passed throughout. They imported the module on a Python that hides
the mistake.

Resolving each provider's hints here forces the same evaluation 3.12 does, so
a misordered definition fails in CI rather than at boot.
"""

import typing

import pytest

import app.api.deps as deps

PROVIDERS = [
    getattr(deps, name)
    for name in dir(deps)
    if callable(getattr(deps, name))
    and getattr(getattr(deps, name), "__module__", "") == "app.api.deps"
]


def test_there_are_providers_to_check():
    """Guards the guard: a filter that silently matches nothing proves nothing."""
    assert len(PROVIDERS) > 20


@pytest.mark.parametrize("provider", PROVIDERS, ids=lambda p: p.__name__)
def test_every_annotation_resolves(provider):
    try:
        typing.get_type_hints(provider)
    except NameError as exc:
        pytest.fail(
            f"{provider.__name__} refers to {exc} before it is defined. "
            "This boots on Python 3.14 and crashes on the 3.12 in the "
            "Dockerfile — move the definition above its first use."
        )
