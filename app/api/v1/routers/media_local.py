"""Serves and accepts media in local development only.

In production Cloudflare does this and the API never sees a byte. Locally there
is no bucket, so these two routes stand in for one — which is precisely why the
config guard refuses `MEDIA_BACKEND=local` anywhere else.

There is no session check here, deliberately. A signed URL *is* the
authorisation, exactly as it is with a real provider: the signature covers the
key, the verb and an expiry, and none of those can be edited without breaking
it. Requiring a cookie as well would make these routes behave unlike the thing
they are imitating, and hide mistakes until production.
"""

from fastapi import APIRouter, HTTPException, Query, Request, Response, status

from app.api.deps import MediaStorageDep
from app.core.content_disposition import attachment
from app.infrastructure.storage.local_media_storage import LocalMediaStorage

router = APIRouter(prefix="/media", tags=["media"], include_in_schema=False)


def _local(storage) -> LocalMediaStorage:
    if not isinstance(storage, LocalMediaStorage):
        # Reached only if someone points a deployed environment at these
        # routes. Saying so beats a confusing 500.
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "This endpoint exists only when media is stored on local disk.",
        )
    return storage


@router.put("/parts/{upload_id}/{part}")
async def put_part(
    upload_id: str,
    part: int,
    request: Request,
    storage: MediaStorageDep,
    expires: int = Query(...),
    signature: str = Query(...),
) -> Response:
    """Accept one chunk, answering with an identifier as a provider would."""
    disk = _local(storage)
    if not disk.verify(
        payload=f"PUT:{upload_id}:{part}", expires_at=expires, signature=signature
    ):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "That upload link has expired.")

    etag = disk.write_part(upload_id=upload_id, part=part, data=await request.body())
    # Quoted, because S3 quotes them and the completion call compares strings.
    return Response(status_code=status.HTTP_200_OK, headers={"ETag": f'"{etag}"'})


@router.get("/{key:path}")
async def get_object(
    key: str,
    storage: MediaStorageDep,
    expires: int = Query(...),
    signature: str = Query(...),
    filename: str | None = Query(None),
) -> Response:
    """Serve the object, inline to look at or as a download to keep.

    `filename` is part of the signed payload, not decoration on the end of
    it — see `presign_download`. So a link minted for viewing cannot have a
    name appended to it to turn it into a download, which is the same
    property the real provider has.
    """
    disk = _local(storage)
    payload = f"GET:{key}" if filename is None else f"GET:{key}:{filename}"
    if not disk.verify(payload=payload, expires_at=expires, signature=signature):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "That link has expired.")

    data = disk.read_bytes(key=key)
    if data is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such object.")
    return Response(
        content=data,
        media_type="application/octet-stream",
        headers={"Content-Disposition": attachment(filename)} if filename else None,
    )
