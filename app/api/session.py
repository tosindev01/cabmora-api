"""Session-cookie mechanics.

Deliberately in the api layer, not `core`: setting a cookie is an HTTP detail.
`LoginUser` still returns a token and knows nothing about browsers, so the same
use case serves the SPA, a mobile client and a CLI without changing.
"""

from fastapi import Response

from app.core.config import get_settings


def set_session_cookie(response: Response, token: str) -> None:
    """Attach the signed-in session to the response."""
    settings = get_settings()
    response.set_cookie(
        key=settings.session_cookie_name,
        value=token,
        max_age=settings.access_token_expire_minutes * 60,
        httponly=True,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    """Expire the session cookie.

    The attributes must match the ones it was set with or the browser keeps the
    original cookie alongside the expired one and the user stays signed in.
    """
    settings = get_settings()
    response.delete_cookie(
        key=settings.session_cookie_name,
        path="/",
        httponly=True,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,
    )
