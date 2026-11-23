"""Cloudflare R2, spoken through its S3-compatible API.

Two things shape this class.

**Signing is free; talking is not.** Generating a presigned URL is pure
computation — no network, no blocking — so those calls happen inline. The four
operations that really do reach Cloudflare (completing an upload, abandoning
one, checking an object, deleting it) run in a worker thread, because boto3 is
synchronous and a blocking call here would stall every other request the API is
serving while a photographer waits.

**The bucket's jurisdiction is part of its address.** An EU bucket answers on
`<account>.eu.r2.cloudflarestorage.com`, and using the wrong host produces a
signature error rather than a helpful 404 — which is why the endpoint is
derived from config rather than typed.
"""

import asyncio
import logging
from typing import Any

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError

from app.domain.services.media_storage import PART_SIZE, MediaStorage, UploadTicket
from app.core.content_disposition import attachment

logger = logging.getLogger(__name__)

#: How long a browser has to use the URLs it was handed. Long enough for a slow
#: connection to push a large file, short enough that a URL copied out of the
#: network tab stops working the same afternoon.
UPLOAD_TTL = 6 * 60 * 60


class R2MediaStorage(MediaStorage):
    def __init__(
        self,
        *,
        endpoint: str,
        bucket: str,
        access_key_id: str,
        secret_access_key: str,
    ) -> None:
        self._bucket = bucket
        self._client = boto3.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
            # R2 ignores the region but the signer insists on one, and it must
            # match what R2 expects or every signature is rejected.
            region_name="auto",
            config=Config(
                signature_version="s3v4",
                # R2 does not implement the checksum headers boto3 began
                # sending by default, and a request carrying them is refused.
                request_checksum_calculation="when_required",
                response_checksum_validation="when_required",
                retries={"max_attempts": 3, "mode": "standard"},
            ),
        )

    async def _call(self, method: str, **kwargs: Any) -> Any:
        """Run a blocking boto3 call without stalling the event loop."""
        return await asyncio.to_thread(getattr(self._client, method), **kwargs)

    # ── uploads ──────────────────────────────────────────────────────────
    async def start_upload(
        self, *, key: str, content_type: str, byte_size: int
    ) -> UploadTicket:
        created = await self._call(
            "create_multipart_upload",
            Bucket=self._bucket,
            Key=key,
            ContentType=content_type,
        )
        upload_id = created["UploadId"]

        # `max(1, ...)` so a zero-byte file still gets one part rather than a
        # ticket with no URLs, which could never be completed.
        parts = max(1, -(-byte_size // PART_SIZE))
        part_urls = [
            self._client.generate_presigned_url(
                "upload_part",
                Params={
                    "Bucket": self._bucket,
                    "Key": key,
                    "UploadId": upload_id,
                    "PartNumber": n,
                },
                ExpiresIn=UPLOAD_TTL,
            )
            for n in range(1, parts + 1)
        ]
        logger.info("[r2] upload %s started for %s (%d parts)", upload_id, key, parts)
        return UploadTicket(upload_id=upload_id, part_size=PART_SIZE, part_urls=part_urls)

    async def complete_upload(self, *, key: str, upload_id: str, etags: list[str]) -> None:
        await self._call(
            "complete_multipart_upload",
            Bucket=self._bucket,
            Key=key,
            UploadId=upload_id,
            MultipartUpload={
                "Parts": [
                    # Position is what reassembles the file — the caller must
                    # hand these over in part order or the result is a corrupt
                    # object rather than an error.
                    {"PartNumber": n, "ETag": etag}
                    for n, etag in enumerate(etags, start=1)
                ]
            },
        )
        logger.info("[r2] upload %s completed for %s", upload_id, key)

    async def abort_upload(self, *, key: str, upload_id: str) -> None:
        try:
            await self._call(
                "abort_multipart_upload",
                Bucket=self._bucket, Key=key, UploadId=upload_id,
            )
        except ClientError as exc:
            # Already gone — the bucket's own 7-day rule may have swept it.
            # Abandoning something twice is not a failure worth raising.
            if exc.response.get("Error", {}).get("Code") != "NoSuchUpload":
                raise

    # ── delivery ─────────────────────────────────────────────────────────
    async def presign_download(
        self, *, key: str, expires_in: int = 300, as_filename: str | None = None
    ) -> str:
        params: dict[str, str] = {"Bucket": self._bucket, "Key": key}
        if as_filename is not None:
            # Signed into the URL, so it cannot be edited off it: S3 and R2
            # fold `response-content-disposition` into the signature, and a
            # tampered copy fails to verify rather than serving inline.
            params["ResponseContentDisposition"] = attachment(as_filename)
        return self._client.generate_presigned_url(
            "get_object",
            Params=params,
            ExpiresIn=expires_in,
        )

    async def exists(self, *, key: str) -> int | None:
        try:
            head = await self._call("head_object", Bucket=self._bucket, Key=key)
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in {"404", "NoSuchKey"}:
                return None
            raise
        return int(head["ContentLength"])

    async def delete(self, *, key: str) -> None:
        await self._call("delete_object", Bucket=self._bucket, Key=key)

    # ── server-side only ─────────────────────────────────────────────────
    async def read(self, *, key: str) -> bytes:
        response = await self._call("get_object", Bucket=self._bucket, Key=key)
        return await asyncio.to_thread(response["Body"].read)

    async def write(self, *, key: str, data: bytes, content_type: str) -> None:
        # A single PUT, not multipart: these are renditions the server just
        # made, measured in hundreds of kilobytes, and nothing is resuming.
        await self._call(
            "put_object",
            Bucket=self._bucket, Key=key, Body=data, ContentType=content_type,
        )
