import logging
from typing import Annotated

from fastapi import APIRouter, Depends, File, Response, UploadFile, status

from app.api import throttle
from app.api.deps import (
    CurrentActiveUserDep,
    MediaStorageDep,
    OptionalStorageDep,
    get_change_password,
    get_get_preferences,
    get_update_preferences,
    get_change_avatar,
    get_update_profile,
    CurrentUserDep,
    get_accept_invite,
    get_request_password_reset,
    get_reset_password,
    get_login_user,
    get_register_user,
)
from app.api.session import clear_session_cookie, set_session_cookie
from app.core.exceptions import AuthenticationError
from app.application.use_cases.invites.provision_account import CONSOLE_ROLES
from app.core.config import get_settings
from app.domain.entities.user import UserRole
from app.api.schemas.auth import (
    AvatarConfirmRequest,
    AvatarUploadRequest,
    AvatarUploadResponse,
    ChangePasswordRequest,
    PreferencesResponse,
    PreferencesUpdateRequest,
    ProfileUpdateRequest,
    AcceptInviteRequest,
    ForgotPasswordRequest,
    ResetPasswordRequest,
    LoginRequest,
    RegisterRequest,
    TokenResponse,
    UserResponse,
)
from app.application.use_cases.auth.login_user import LoginUser
from app.application.use_cases.auth.register_user import RegisterUser
from app.domain.services.media_storage import MediaStorage
from app.application.use_cases.account.change_avatar import (
    MAX_BYTES as MAX_AVATAR_BYTES,
    ChangeAvatar,
)
from app.application.use_cases.account.change_password import ChangePassword
from app.application.use_cases.account.preferences import (
    GetPreferences,
    PreferenceChanges,
    UpdatePreferences,
)
from app.domain.entities.preferences import (
    DATE_FORMATS,
    SUPPORTED_CURRENCIES,
    SUPPORTED_LANGUAGES,
    NotificationKind,
    UserPreferences,
)
from app.application.use_cases.account.update_profile import ProfileChanges, UpdateProfile
from app.application.use_cases.auth.request_password_reset import RequestPasswordReset
from app.application.use_cases.auth.reset_password import ResetPassword
from app.application.use_cases.invites.accept_invite import AcceptInvite

logger = logging.getLogger(__name__)

#: Same wording for an exhausted invite link and an exhausted reset link —
#: which kind of link somebody is holding is not something to confirm.
_LINK_REFUSAL = "This link has been tried too many times. Request a new one."

router = APIRouter(prefix="/auth", tags=["auth"])


#: Roles whose work is in the console rather than on the public site.
#: Mirrors `ProvisionAccount.CONSOLE_ROLES` — imported rather than retyped, so
#: a third staff role cannot be added to one list and forgotten in the other.
def _console_url_for(role: UserRole) -> str | None:
    """The console's address, for the people who belong in it.

    Returned on every auth response rather than only on login, because a staff
    member who is already signed in and opens the public site needs the same
    answer — and `/me` is the only thing that screen asks.

    None when `ADMIN_BASE_URL` is unset. The caller must then leave them where
    they are rather than invent a host: a redirect to a guessed origin is how
    somebody ends up on a 404 with no way back.
    """
    if role not in CONSOLE_ROLES:
        return None
    return get_settings().admin_base_url


def _to_user_response(user, avatar_url: str | None = None) -> UserResponse:
    return UserResponse(
        id=user.id,
        email=user.email,
        first_name=user.first_name,
        last_name=user.last_name,
        full_name=user.full_name,  # derived property on the entity
        # These two were in the schema but never passed, so every response
        # said the account had no phone number regardless of the row.
        phone=user.phone,
        whatsapp=user.whatsapp,
        avatar_url=avatar_url,
        role=user.role,
        status=user.status,
        granted=sorted(user.granted, key=lambda p: p.value),
        from_groups=sorted(user.from_groups, key=lambda p: p.value),
        group_names=user.group_names,
        reachable=sorted(user.reachable, key=lambda p: p.value),
        console_url=_console_url_for(user.role),
        created_at=user.created_at,
    )


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register(
    body: RegisterRequest,
    use_case: Annotated[RegisterUser, Depends(get_register_user)],
) -> UserResponse:
    user = await use_case.execute(
        email=body.email,
        first_name=body.first_name,
        last_name=body.last_name,
        password=body.password,
        account_type=body.account_type,
    )
    return _to_user_response(user)


@router.post("/login", response_model=TokenResponse)
async def login(
    body: LoginRequest,
    response: Response,
    use_case: Annotated[LoginUser, Depends(get_login_user)],
) -> TokenResponse:
    """Sign in.

    Sets an HttpOnly session cookie *and* returns the token in the body. The
    cookie is what the browser uses — script cannot read it, so an XSS on a
    portal page cannot lift the session. The body is for clients that have no
    cookie jar (mobile, CI, curl); browsers should ignore it rather than
    copying it into localStorage, which would give the token back to script and
    undo the point of the exercise.
    """
    key = f"login:{body.email.strip().lower()}"
    throttle.guard(
        key,
        throttle.LOGIN,
        "Too many sign-in attempts for this account. Wait a few minutes, or "
        "use 'Forgot password?' to send yourself a reset link.",
    )

    try:
        result = await use_case.execute(email=body.email, password=body.password)
    except AuthenticationError:
        # Counted here rather than in the use case: the use case answers
        # "are these credentials good", which the tests and the CLI ask too.
        # How often a stranger may ask is a question about the front door.
        throttle.record_failure(key, throttle.LOGIN)
        logger.info("[auth] failed sign-in for %s", body.email)
        raise

    # Cleared on success, so a few fumbled attempts never accumulate.
    throttle.forget(key)
    set_session_cookie(response, result.access_token)
    return TokenResponse(
        access_token=result.access_token,
        token_type=result.token_type,
        user=_to_user_response(result.user),
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(response: Response) -> None:
    """Sign out by expiring the session cookie.

    Deliberately does not require authentication: clearing a cookie you may not
    have is harmless, and a user whose token has already expired still needs
    the stale cookie removed rather than a 401.
    """
    clear_session_cookie(response)


async def _avatar_url(user, storage: MediaStorage | None) -> str | None:
    """Mint a short-lived URL for the picture, or None.

    Swallows storage failures on purpose. A bucket that is unconfigured or
    briefly unreachable must not make `GET /auth/me` fail — the caller loses an
    avatar, not their session.
    """
    if user.avatar_key is None or storage is None:
        return None
    try:
        return await storage.presign_download(key=user.avatar_key, expires_in=900)
    except Exception:
        return None


@router.get("/me", response_model=UserResponse)
async def me(current_user: CurrentUserDep, storage: OptionalStorageDep) -> UserResponse:
    return _to_user_response(current_user, await _avatar_url(current_user, storage))


@router.patch("/me", response_model=UserResponse)
async def update_me(
    body: ProfileUpdateRequest,
    current_user: CurrentActiveUserDep,
    storage: OptionalStorageDep,
    use_case: Annotated[UpdateProfile, Depends(get_update_profile)],
) -> UserResponse:
    """Edit your own details.

    No id in the path: the actor is the subject, so there is no ownership check
    to forget. An admin changing somebody else's record goes through
    `/admin/users/{id}`, which is guarded separately.
    """
    updated = await use_case.execute(
        actor=current_user,
        changes=ProfileChanges(
            first_name=body.first_name,
            last_name=body.last_name,
            phone=body.phone,
            whatsapp=body.whatsapp,
        ),
    )
    return _to_user_response(updated, await _avatar_url(updated, storage))


@router.post("/me/password", status_code=status.HTTP_204_NO_CONTENT)
async def change_my_password(
    body: ChangePasswordRequest,
    current_user: CurrentActiveUserDep,
    use_case: Annotated[ChangePassword, Depends(get_change_password)],
) -> None:
    """Change your own password, proving you know the current one.

    No new cookie is issued. The session is already this person's, and the
    bearer tokens other clients hold stay valid until they expire — revoking
    them needs server-side sessions, which do not exist yet.
    """
    await use_case.execute(
        actor=current_user, current=body.current_password, new=body.new_password
    )


@router.post("/me/avatar", response_model=UserResponse)
async def change_avatar(
    current_user: CurrentActiveUserDep,
    storage: MediaStorageDep,
    use_case: Annotated[ChangeAvatar, Depends(get_change_avatar)],
    file: Annotated[UploadFile, File(description="JPEG, PNG or WebP, up to 8 MB")],
) -> UserResponse:
    """The picture itself, in one request.

    This used to hand back signed URLs for the browser to PUT to the bucket,
    then take a second call to confirm. That is the right shape for a 40 GB
    film and the wrong one for a profile photograph: it needed a CORS policy
    and an exposed ETag header to work at all, and failed silently when
    either was missing.
    """
    # Read with the ceiling in mind rather than after the fact: an 8 MB limit
    # enforced once the whole file is in memory is not a limit.
    data = await file.read(MAX_AVATAR_BYTES + 1)
    updated = await use_case.execute(
        actor=current_user,
        data=data,
        content_type=(file.content_type or "").split(";")[0].strip(),
    )
    return _to_user_response(updated, await _avatar_url(updated, storage))


@router.post("/accept-invite", response_model=TokenResponse)
async def accept_invite(
    body: AcceptInviteRequest,
    response: Response,
    accept: Annotated[AcceptInvite, Depends(get_accept_invite)],
    login: Annotated[LoginUser, Depends(get_login_user)],
) -> TokenResponse:
    """Set a password from an invite link, and sign in.

    Signing in here is deliberate: the customer has just proved they hold a
    single-use link sent to their address and chosen a password. Sending them
    to a login form to type it again adds friction and no security.
    """
    key = f"invite:{body.token[:16]}"
    throttle.guard(key, throttle.LINK_REDEMPTION, _LINK_REFUSAL)
    try:
        user = await accept.execute(token=body.token, password=body.password)
    except AuthenticationError:
        throttle.record_failure(key, throttle.LINK_REDEMPTION)
        raise

    throttle.forget(key)
    result = await login.execute(email=user.email, password=body.password)
    set_session_cookie(response, result.access_token)
    return TokenResponse(
        access_token=result.access_token,
        token_type=result.token_type,
        user=_to_user_response(result.user),
    )


@router.post("/forgot-password", status_code=status.HTTP_204_NO_CONTENT)
async def forgot_password(
    body: ForgotPasswordRequest,
    use_case: Annotated[RequestPasswordReset, Depends(get_request_password_reset)],
) -> None:
    """Send a reset link, if there is anywhere to send it.

    Always 204, whatever happened. The response must look identical for an
    address with an account and one without, or this endpoint becomes a way
    to ask whether a given person is a Cabmora client.
    """
    # Keyed by the address, because the abuse here is using somebody else's
    # inbox as a target. Refusing does not leak whether the account exists —
    # the count is of requests, not of accounts found.
    throttle.guard(
        f"reset-request:{body.email.strip().lower()}",
        throttle.RESET_REQUEST,
        "A reset link has already been requested for that address. "
        "Check your inbox, or try again shortly.",
    )
    throttle.record_failure(
        f"reset-request:{body.email.strip().lower()}", throttle.RESET_REQUEST
    )
    await use_case.execute(body.email)


@router.post("/reset-password", response_model=TokenResponse)
async def reset_password(
    body: ResetPasswordRequest,
    response: Response,
    reset: Annotated[ResetPassword, Depends(get_reset_password)],
    login: Annotated[LoginUser, Depends(get_login_user)],
) -> TokenResponse:
    """Choose a new password from a reset link, and sign in.

    Signed in for the same reason as an accepted invite: they have just proved
    they hold a single-use link sent to their address and chosen the password.
    """
    key = f"reset:{body.token[:16]}"
    throttle.guard(key, throttle.LINK_REDEMPTION, _LINK_REFUSAL)
    try:
        user = await reset.execute(token=body.token, password=body.password)
    except AuthenticationError:
        throttle.record_failure(key, throttle.LINK_REDEMPTION)
        raise

    throttle.forget(key)
    result = await login.execute(email=user.email, password=body.password)
    set_session_cookie(response, result.access_token)
    return TokenResponse(
        access_token=result.access_token,
        token_type=result.token_type,
        user=_to_user_response(result.user),
    )


def _preferences_response(preferences: UserPreferences) -> PreferencesResponse:
    return PreferencesResponse(
        currency=preferences.currency,
        language=preferences.language,
        timezone=preferences.timezone,
        date_format=preferences.date_format,
        muted=sorted(preferences.muted, key=lambda kind: kind.value),
        # Sent with every response so the settings screen offers exactly what
        # this server accepts. A hardcoded list in the frontend drifts, and the
        # first anyone hears of it is a 422 on save.
        available_currencies=list(SUPPORTED_CURRENCIES),
        available_languages=list(SUPPORTED_LANGUAGES),
        available_date_formats=list(DATE_FORMATS),
        mutable_notifications=list(NotificationKind),
    )


@router.get("/me/preferences", response_model=PreferencesResponse)
async def my_preferences(
    actor: CurrentActiveUserDep,
    use_case: Annotated[GetPreferences, Depends(get_get_preferences)],
) -> PreferencesResponse:
    """Their settings, or the defaults. Never a 404 — an account that has
    never changed anything still has preferences, they are just untouched."""
    return _preferences_response(await use_case.execute(actor=actor))


@router.patch("/me/preferences", response_model=PreferencesResponse)
async def update_my_preferences(
    body: PreferencesUpdateRequest,
    actor: CurrentActiveUserDep,
    use_case: Annotated[UpdatePreferences, Depends(get_update_preferences)],
) -> PreferencesResponse:
    return _preferences_response(
        await use_case.execute(
            actor=actor,
            changes=PreferenceChanges(
                currency=body.currency,
                language=body.language,
                timezone=body.timezone,
                date_format=body.date_format,
                muted=set(body.muted) if body.muted is not None else None,
            ),
        )
    )
