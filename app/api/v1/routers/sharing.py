"""Share links: the owner's side, and the public side.

Two routers because they have nothing in common but the table. One is guarded
and belongs to whoever owns the project; the other is the only unauthenticated
read of anybody's photographs in the system and is deliberately narrow.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.api.deps import (
    CurrentActiveUserDep,
    get_manage_shares,
    get_view_shared_gallery,
)
from app.api.schemas.sharing import (
    IssuedShareResponse,
    ShareCreateRequest,
    ShareResponse,
    SharedGalleryResponse,
    SharedPhotographResponse,
)
from app.application.use_cases.sharing.manage_shares import ManageGalleryShares
from app.application.use_cases.sharing.view_shared_gallery import ViewSharedGallery
from app.core.config import get_settings
from app.domain.entities.gallery_share import GalleryShare

router = APIRouter(prefix="/projects/{project_id}/shares", tags=["sharing"])
public_router = APIRouter(prefix="/shared", tags=["sharing"])


def _share(share: GalleryShare) -> ShareResponse:
    return ShareResponse(
        id=share.id,
        label=share.label,
        created_at=share.created_at,
        expires_at=share.expires_at,
        revoked_at=share.revoked_at,
        last_viewed_at=share.last_viewed_at,
        views=share.views,
        active=share.is_usable,
        # None for a whole-gallery link, so the browser can tell "everything"
        # from a selective link that is now empty.
        photograph_count=len(share.asset_ids) if share.selective else None,
    )


@router.post("", response_model=IssuedShareResponse, status_code=status.HTTP_201_CREATED)
async def create_share(
    project_id: UUID,
    body: ShareCreateRequest,
    actor: CurrentActiveUserDep,
    use_case: Annotated[ManageGalleryShares, Depends(get_manage_shares)],
) -> IssuedShareResponse:
    """Hand out a link. The URL comes back once and cannot be recovered.

    `asset_ids` picks the photographs behind it; omitting it shares the
    gallery, as every link did before the choice existed.
    """
    issued = await use_case.create(
        project_id=project_id,
        actor=actor,
        label=body.label,
        asset_ids=body.asset_ids,
    )
    base = get_settings().public_base_url.rstrip("/")
    return IssuedShareResponse(
        **_share(issued.share).model_dump(),
        url=f"{base}/s/{issued.token}",
    )


@router.get("", response_model=list[ShareResponse])
async def list_shares(
    project_id: UUID,
    actor: CurrentActiveUserDep,
    use_case: Annotated[ManageGalleryShares, Depends(get_manage_shares)],
) -> list[ShareResponse]:
    return [
        _share(share)
        for share in await use_case.list_for_project(project_id=project_id, actor=actor)
    ]


@router.delete("/{share_id}", response_model=ShareResponse)
async def revoke_share(
    project_id: UUID,
    share_id: UUID,
    actor: CurrentActiveUserDep,
    use_case: Annotated[ManageGalleryShares, Depends(get_manage_shares)],
) -> ShareResponse:
    """Stop a link working. The record stays — who shared this, and when did
    we stop it, is the question asked afterwards."""
    return _share(await use_case.revoke(share_id=share_id, actor=actor))


@public_router.get("/{token}", response_model=SharedGalleryResponse)
async def view_shared_gallery(
    token: str,
    use_case: Annotated[ViewSharedGallery, Depends(get_view_shared_gallery)],
) -> SharedGalleryResponse:
    """The photographs behind a link. No account required.

    Deliberately thin: the project's title and its released photographs, under
    exactly the rules that already apply to its client. Holding a link widens
    nothing — in particular it does not lift the watermark, which comes off
    when the job is paid for and not before.
    """
    gallery = await use_case.execute(token)
    return SharedGalleryResponse(
        project_title=gallery.project_title,
        event_type=gallery.event_type,
        photographs=[
            SharedPhotographResponse(
                id=p.id, filename=p.filename, url=p.url, content_type=p.content_type
            )
            for p in gallery.photographs
        ],
        expires_at=gallery.expires_at,
        hands_over_originals=gallery.hands_over_originals,
    )
