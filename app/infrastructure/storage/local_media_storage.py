"""Files on disk, for development and tests.

The counterpart to `LoggingEmailSender`: it satisfies the port honestly without
needing a Cloudflare account, so the whole upload flow can be built and tested
before credentials exist.

Its "presigned" URLs are signed with the app's own secret and served by a route
in this API — the one place bytes legitimately pass through the container,
because locally there is no bucket to talk to instead. That is a development
convenience, and exactly why the config guard refuses this class outside local.
"""

import hashlib
import hmac
import json
import logging
import time
from pathlib import Path
from urllib.parse import quote
from uuid import uuid4

from app.domain.services.media_storage import PART_SIZE, MediaStorage, UploadTicket

logger = logging.getLogger(__name__)


class LocalMediaStorage(MediaStorage):
    def __init__(self, *, root: Path, secret: str, base_url: str) -> None:
        self._root = root
        self._secret = secret.encode()
        self._base_url = base_url.rstrip("/")
        self._root.mkdir(parents=True, exist_ok=True)
        #: Parts land here until assembled, mirroring how a provider holds them
        #: apart from the finished object.
        self._staging = self._root / ".uploads"
        self._staging.mkdir(parents=True, exist_ok=True)

    # ── paths ────────────────────────────────────────────────────────────
    def _path(self, key: str) -> Path:
        # `key` is built from a hex digest, never from user input, but a
        # traversal check costs nothing and the invariant should be local.
        resolved = (self._root / key).resolve()
        if not resolved.is_relative_to(self._root.resolve()):
            raise ValueError(f"Refusing a key that escapes the media root: {key!r}")
        return resolved

    def _part_path(self, upload_id: str, part: int) -> Path:
        return self._staging / upload_id / f"{part:05d}"

    # ── signing ──────────────────────────────────────────────────────────
    def _sign(self, payload: str, expires_at: int) -> str:
        return hmac.new(
            self._secret, f"{payload}:{expires_at}".encode(), hashlib.sha256
        ).hexdigest()

    def _url(self, path: str, payload: str, expires_in: int) -> str:
        expires_at = int(time.time()) + expires_in
        return (
            f"{self._base_url}/media/{path}"
            f"?expires={expires_at}&signature={self._sign(payload, expires_at)}"
        )

    def verify(self, *, payload: str, expires_at: int, signature: str) -> bool:
        """Checked by the local media route before it serves or accepts anything."""
        if expires_at < int(time.time()):
            return False
        return hmac.compare_digest(self._sign(payload, expires_at), signature)

    # ── the port ─────────────────────────────────────────────────────────
    async def start_upload(
        self, *, key: str, content_type: str, byte_size: int
    ) -> UploadTicket:
        upload_id = uuid4().hex
        (self._staging / upload_id).mkdir(parents=True, exist_ok=True)
        # `max(1, ...)` so a zero-byte file still gets one part rather than a
        # ticket with no URLs, which would be impossible to complete.
        parts = max(1, -(-byte_size // PART_SIZE))
        (self._staging / upload_id / "meta.json").write_text(
            json.dumps({"key": key, "content_type": content_type, "parts": parts})
        )
        return UploadTicket(
            upload_id=upload_id,
            part_size=PART_SIZE,
            part_urls=[
                self._url(
                    f"parts/{upload_id}/{n}",
                    f"PUT:{upload_id}:{n}",
                    expires_in=3600,
                )
                for n in range(1, parts + 1)
            ],
        )

    async def complete_upload(self, *, key: str, upload_id: str, etags: list[str]) -> None:
        staged = self._staging / upload_id
        if not staged.is_dir():
            raise ValueError(f"No upload in progress: {upload_id!r}")

        # Every part is checked *before* anything is written. Discovering a
        # missing chunk halfway through would leave a truncated file at the
        # destination — and a half-written photograph is worse than an error,
        # because it looks like a file and opens as corruption.
        parts = []
        for n in range(1, len(etags) + 1):
            part = self._part_path(upload_id, n)
            if not part.is_file():
                raise ValueError(f"Part {n} of {upload_id} was never uploaded")
            parts.append(part)

        destination = self._path(key)
        destination.parent.mkdir(parents=True, exist_ok=True)
        # Assembled beside the destination and moved into place in one step, so
        # a crash mid-write cannot leave a partial object either. Concatenated
        # in part order, which is what a provider does — and why the caller must
        # not reorder the list it collected.
        staging_file = destination.with_suffix(destination.suffix + ".partial")
        with staging_file.open("wb") as out:
            for part in parts:
                out.write(part.read_bytes())
        staging_file.replace(destination)

        for leftover in staged.iterdir():
            leftover.unlink()
        staged.rmdir()

    async def abort_upload(self, *, key: str, upload_id: str) -> None:
        staged = self._staging / upload_id
        if not staged.is_dir():
            return
        for leftover in staged.iterdir():
            leftover.unlink()
        staged.rmdir()

    async def presign_download(
        self, *, key: str, expires_in: int = 300, as_filename: str | None = None
    ) -> str:
        if as_filename is None:
            return self._url(quote(key), f"GET:{key}", expires_in)
        # The name goes into the signed payload as well as the query string.
        # R2 folds the disposition into its signature, so a link there cannot
        # be edited to serve inline; signing it here too keeps the stand-in
        # behaving like the thing it stands in for, which is the whole point
        # of these routes.
        url = self._url(quote(key), f"GET:{key}:{as_filename}", expires_in)
        return f"{url}&filename={quote(as_filename)}"

    async def exists(self, *, key: str) -> int | None:
        path = self._path(key)
        return path.stat().st_size if path.is_file() else None

    async def delete(self, *, key: str) -> None:
        path = self._path(key)
        if path.is_file():
            path.unlink()

    async def read(self, *, key: str) -> bytes:
        data = self.read_bytes(key=key)
        if data is None:
            raise FileNotFoundError(key)
        return data

    async def write(self, *, key: str, data: bytes, content_type: str) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    # ── used by the local media route, not part of the port ──
    def write_part(self, *, upload_id: str, part: int, data: bytes) -> str:
        """Stores one chunk and returns its identifier, as a provider would."""
        path = self._part_path(upload_id, part)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return hashlib.md5(data).hexdigest()

    def read_bytes(self, *, key: str) -> bytes | None:
        """Synchronous sibling of `read`, used by the local media route."""
        path = self._path(key)
        return path.read_bytes() if path.is_file() else None
