"""Upload endpoints.

Two calls per file, and the bytes go through neither of them. The API says
where to put a file and later confirms it arrived; Cloudflare carries the
photograph itself. That is not an optimisation — routing media through this
container would pay Railway egress twice, hold gigabytes in memory and die on
request timeouts.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, status

from app.api.deps import (
    CurrentActiveUserDep,
    CurrentStaffDep,
    get_confirm_upload,
    get_delete_asset,
    get_list_asset_versions,
    get_list_project_assets,
    get_preview_release,
    get_release_assets,
    get_render_asset,
    get_request_upload,
    RenderAsset,
    DownloadAssetDep,
    ListMyMediaDep,
    ManageFoldersDep,
)
from app.api.schemas.media import (
    AssetResponse,
    AssetVersionResponse,
    ConfirmUploadRequest,
    DeletedAssetsResponse,
    ReleasePreviewResponse,
    ReleaseRequest,
    UploadAuthorisationResponse,
    UploadRequest,
    UploadTicketResponse,
    VisibleAssetResponse,
    CreateFolderRequest,
    FileAssetsRequest,
    FiledResponse,
    FolderResponse,
    DownloadLinkResponse,
    LibraryItemResponse,
    RenameFolderRequest,
    ReorderFoldersRequest,
)
from app.application.use_cases.media.delete_asset import DeleteAsset
from app.application.use_cases.media.confirm_upload import ConfirmUpload
from app.application.use_cases.media.list_asset_versions import ListAssetVersions
from app.application.use_cases.media.list_project_assets import ListProjectAssets
from app.application.use_cases.media.preview_release import PreviewRelease
from app.application.use_cases.media.release_assets import ReleaseAssets
from app.application.use_cases.media.request_upload import RequestUpload
from app.domain.entities.asset import Asset

router = APIRouter(prefix="/projects/{project_id}/uploads", tags=["media"])


def _asset(asset: Asset) -> AssetResponse:
    return AssetResponse(
        id=asset.id,
        project_id=asset.project_id,
        filename=asset.filename,
        kind=asset.kind.value,
        content_hash=asset.content_hash,
        renditions_ready=asset.renditions_ready_at is not None,
        released=asset.is_released,
        folder_id=asset.folder_id,
    )


@router.post("", response_model=UploadAuthorisationResponse)
async def request_upload(
    project_id: UUID,
    body: UploadRequest,
    actor: CurrentActiveUserDep,
    use_case: Annotated[RequestUpload, Depends(get_request_upload)],
) -> UploadAuthorisationResponse:
    """Ask where to put a file — or learn it is already held.

    200 rather than 201 in both cases: nothing was created when the answer is
    a ticket, and when the answer is an existing asset the client did not
    cause the creation of the bytes it now points at.
    """
    result = await use_case.execute(
        project_id=project_id,
        actor=actor,
        content_hash=body.content_hash,
        filename=body.filename,
        content_type=body.content_type,
        byte_size=body.byte_size,
    )
    return UploadAuthorisationResponse(
        key=result.key,
        ticket=(
            UploadTicketResponse(
                upload_id=result.ticket.upload_id,
                part_size=result.ticket.part_size,
                part_urls=result.ticket.part_urls,
            )
            if result.ticket
            else None
        ),
        asset=_asset(result.asset) if result.asset else None,
    )


@router.post("/confirm", response_model=AssetResponse, status_code=status.HTTP_201_CREATED)
async def confirm_upload(
    project_id: UUID,
    body: ConfirmUploadRequest,
    actor: CurrentActiveUserDep,
    background: BackgroundTasks,
    use_case: Annotated[ConfirmUpload, Depends(get_confirm_upload)],
    render: Annotated[RenderAsset, Depends(get_render_asset)],
) -> AssetResponse:
    """Assemble the parts and record the file, once it really is there."""
    asset = await use_case.execute(
        project_id=project_id,
        actor=actor,
        content_hash=body.content_hash,
        filename=body.filename,
        content_type=body.content_type,
        byte_size=body.byte_size,
        upload_id=body.upload_id,
        etags=body.etags,
        replaces=body.replaces,
    )
    # After the response, not during it: the client gets its confirmation at
    # once, and the preview exists a second or two later instead of whenever
    # a timer next looks. Nothing depends on this succeeding — the scheduled
    # sweep catches anything a restart interrupts — but without it a released
    # photograph is invisible until that sweep runs, which is how six of them
    # stayed invisible indefinitely when the sweep was not running at all.
    background.add_task(render, asset.id)
    return _asset(asset)


assets_router = APIRouter(prefix="/projects/{project_id}/assets", tags=["media"])


@assets_router.get("", response_model=list[VisibleAssetResponse])
async def list_assets(
    project_id: UUID,
    actor: CurrentActiveUserDep,
    use_case: Annotated[ListProjectAssets, Depends(get_list_project_assets)],
) -> list[VisibleAssetResponse]:
    """The project's photographs, with links minted for this request only."""
    return [
        VisibleAssetResponse(
            **_asset(item.asset).model_dump(),
            url=item.url,
            is_original=item.is_original,
            content_type=item.content_type,
            superseded_by=item.superseded_by,
            preview_pending=item.asset.awaiting_renditions,
            # `awaiting_renditions` deliberately still covers these: the
            # gallery uses it to decide not to hand over the original's
            # own bytes, and an abandoned asset must stay behind that
            # guard or a failed preview becomes a watermark leak.
            preview_failed=item.asset.renditions_abandoned,
            supersedes_count=item.supersedes_count,
        )
        for item in await use_case.execute(project_id, actor)
    ]


@assets_router.get("/{asset_id}/versions", response_model=list[AssetVersionResponse])
async def list_asset_versions(
    project_id: UUID,
    asset_id: UUID,
    actor: CurrentActiveUserDep,
    use_case: Annotated[ListAssetVersions, Depends(get_list_asset_versions)],
) -> list[AssetVersionResponse]:
    """A photograph and the frames it replaced, newest first.

    Its own request rather than part of the gallery: almost no photograph has
    history, and minting links for it on every gallery load would pay for
    something hardly anybody opens. A list of one means this frame has never
    been corrected.
    """
    return [
        AssetVersionResponse(
            id=version.id,
            filename=version.filename,
            url=version.url,
            uploaded_at=version.uploaded_at,
            is_current=version.is_current,
        )
        for version in await use_case.execute(
            project_id=project_id, asset_id=asset_id, actor=actor
        )
    ]


@assets_router.delete("/{asset_id}", response_model=DeletedAssetsResponse)
async def delete_asset(
    project_id: UUID,
    asset_id: UUID,
    actor: CurrentStaffDep,
    use_case: Annotated[DeleteAsset, Depends(get_delete_asset)],
) -> DeletedAssetsResponse:
    """Remove a photograph, its renditions, and the bytes behind them.

    Staff only. A client reviewing their gallery must never reach this — the
    work they are commenting on is not theirs to destroy.

    `project_id` is in the path for consistency with the rest of this router;
    the asset carries its own project and the use case checks that, so the two
    cannot be used against each other.
    """
    removed = await use_case.execute(asset_id=asset_id, actor=actor)
    return DeletedAssetsResponse(removed=removed)


@assets_router.post("/release", response_model=list[AssetResponse])
async def release_assets(
    project_id: UUID,
    body: ReleaseRequest,
    actor: CurrentActiveUserDep,
    use_case: Annotated[ReleaseAssets, Depends(get_release_assets)],
) -> list[AssetResponse]:
    """Show these photographs to the client, or take them back.

    Returns only what changed, so a console can tell the difference between
    "released four" and "four were already released".
    """
    return [
        _asset(asset)
        for asset in await use_case.execute(
            project_id=project_id,
            actor=actor,
            asset_ids=body.asset_ids,
            released=body.released,
            message=body.message,
        )
    ]


@assets_router.post("/release/preview", response_model=ReleasePreviewResponse)
async def preview_release(
    project_id: UUID,
    body: ReleaseRequest,
    actor: CurrentActiveUserDep,
    use_case: Annotated[PreviewRelease, Depends(get_preview_release)],
) -> ReleasePreviewResponse:
    """What releasing these would do, without doing it.

    A POST that changes nothing, because the question is "what about *these*
    photographs" and a list of forty ids does not belong in a query string.

    It exists so the console can warn before it acts: that an email is about
    to go out, that the project is about to move, that the release mode will
    take photographs nobody picked. Answered here rather than worked out in
    the browser — the frontend would be reimplementing rules this service
    owns, and a confirmation screen that is subtly wrong is worse than none.
    """
    preview = await use_case.execute(
        project_id=project_id,
        actor=actor,
        asset_ids=body.asset_ids,
        released=body.released,
    )
    return ReleasePreviewResponse(
        selected=preview.selected,
        affected=preview.affected,
        preview_pending=preview.preview_pending,
        notifies_client=preview.notifies_client,
        moves_to_stage=preview.moves_to_stage,
        hands_over_originals=preview.hands_over_originals,
    )


library_router = APIRouter(prefix="/me/media", tags=["media"])


@library_router.get("", response_model=list[LibraryItemResponse])
async def my_media(
    actor: CurrentActiveUserDep,
    use_case: ListMyMediaDep,
) -> list[LibraryItemResponse]:
    """Everything this client has been handed, newest first."""
    return [
        LibraryItemResponse(
            id=item.asset.id,
            filename=item.asset.filename,
            url=item.url,
            content_type=item.content_type,
            is_original=item.is_original,
            downloadable=item.downloadable,
            released_at=item.asset.released_at,
            project_id=item.project.id,
            project_title=item.project.title,
            project_event_type=item.project.event_type,
        )
        for item in await use_case.execute(actor=actor)
    ]


@library_router.get("/{asset_id}/download", response_model=DownloadLinkResponse)
async def download_asset(
    asset_id: UUID,
    actor: CurrentActiveUserDep,
    use_case: DownloadAssetDep,
) -> DownloadLinkResponse:
    """A one-shot link that saves this file to the viewer's device.

    The link, not the bytes: media never routes through this container.

    What makes it save rather than open in a tab is the `attachment`
    disposition signed into the URL — a `download` attribute on the anchor
    cannot do it, because the store is a different origin and browsers
    ignore that attribute cross-origin. That is the whole of the bug this
    endpoint exists to fix.

    JSON rather than a 307 so that a refusal is a refusal. Redirecting would
    send somebody whose project has downloads turned off to a page of raw
    error JSON, and this endpoint was written because downloads were failing
    in ways nobody could read.

    Minted per click, so there is no such thing as an expired download link:
    the fifteen-minute view links the gallery holds are what made an
    afternoon-old tab report that the link had expired.
    """
    url = await use_case.execute(actor=actor, asset_id=asset_id)
    return DownloadLinkResponse(url=url)


folders_router = APIRouter(prefix="/projects/{project_id}/folders", tags=["media"])


@folders_router.get("", response_model=list[FolderResponse])
async def list_folders(
    project_id: UUID,
    actor: CurrentActiveUserDep,
    use_case: ManageFoldersDep,
) -> list[FolderResponse]:
    """The parts of this shoot, in running order."""
    return [
        FolderResponse(
            id=folder.id,
            name=folder.name,
            position=folder.position,
            asset_count=folder.asset_count,
        )
        for folder in await use_case.list_folders(actor=actor, project_id=project_id)
    ]


@folders_router.post("", response_model=FolderResponse, status_code=status.HTTP_201_CREATED)
async def create_folder(
    project_id: UUID,
    body: CreateFolderRequest,
    actor: CurrentActiveUserDep,
    use_case: ManageFoldersDep,
) -> FolderResponse:
    folder = await use_case.create(actor=actor, project_id=project_id, name=body.name)
    return FolderResponse(
        id=folder.id,
        name=folder.name,
        position=folder.position,
        asset_count=folder.asset_count,
    )


# Both literal paths are declared before `/{folder_id}`. FastAPI matches in
# definition order, so the other way round "assets" and "order" would be read
# as folder ids and every call to them would 404 on a malformed UUID.
@folders_router.put("/order", response_model=list[FolderResponse])
async def reorder_folders(
    project_id: UUID,
    body: ReorderFoldersRequest,
    actor: CurrentActiveUserDep,
    use_case: ManageFoldersDep,
) -> list[FolderResponse]:
    """Set the running order from the complete list of folder ids."""
    return [
        FolderResponse(
            id=folder.id,
            name=folder.name,
            position=folder.position,
            asset_count=folder.asset_count,
        )
        for folder in await use_case.reorder(
            actor=actor, project_id=project_id, folder_ids=body.folder_ids
        )
    ]


@folders_router.put("/assets", response_model=FiledResponse)
async def file_assets(
    project_id: UUID,
    body: FileAssetsRequest,
    actor: CurrentActiveUserDep,
    use_case: ManageFoldersDep,
) -> FiledResponse:
    """File a batch of photographs, or unfile them with a null folder."""
    moved = await use_case.file_assets(
        actor=actor,
        project_id=project_id,
        asset_ids=body.asset_ids,
        folder_id=body.folder_id,
    )
    return FiledResponse(moved=moved)


@folders_router.patch("/{folder_id}", response_model=FolderResponse)
async def rename_folder(
    project_id: UUID,
    folder_id: UUID,
    body: RenameFolderRequest,
    actor: CurrentActiveUserDep,
    use_case: ManageFoldersDep,
) -> FolderResponse:
    folder = await use_case.rename(
        actor=actor, project_id=project_id, folder_id=folder_id, name=body.name
    )
    return FolderResponse(
        id=folder.id,
        name=folder.name,
        position=folder.position,
        asset_count=folder.asset_count,
    )


@folders_router.delete("/{folder_id}", response_model=FiledResponse)
async def delete_folder(
    project_id: UUID,
    folder_id: UUID,
    actor: CurrentActiveUserDep,
    use_case: ManageFoldersDep,
) -> FiledResponse:
    """Remove a folder. Its photographs are unfiled, never deleted."""
    unfiled = await use_case.delete(
        actor=actor, project_id=project_id, folder_id=folder_id
    )
    return FiledResponse(moved=unfiled)
