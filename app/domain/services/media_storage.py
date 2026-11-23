"""Where bytes live, as an interface the application depends on.

The rule this port exists to enforce: **media never routes through the API.**
Browser → Railway → R2 pays Railway egress twice, holds multi-gigabyte files in
the FastAPI container's memory, and dies on request timeouts. So there is no
`upload(file)` method here and there never should be — the API hands out signed
URLs and the browser talks to the bucket directly.

Uploads are **always multipart**, even for a small photograph. One code path is
worth more than the handful of operations a single-part upload would save: a
40 GB video cannot be sent any other way, and a wedding's 60 MB RAWs would
otherwise restart from zero whenever a connection drops at 90%.

`presign_download` takes a TTL for the same reason the PRD asks for
"non-downloadable" links. That requirement cannot be met literally — anyone who
can see an image can photograph their screen. What a short TTL delivers is that
a copied URL stops working, which is the achievable half.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass

#: 10 MiB. Above R2's 5 MiB minimum for a non-final part, and small enough that
#: a dropped connection costs seconds. At 10,000 parts it ceilings a single
#: file at roughly 100 GB, which is past any deliverable we expect.
PART_SIZE = 10 * 1024 * 1024


@dataclass(frozen=True)
class UploadTicket:
    """Everything the browser needs to send one file, and nothing else."""

    #: The provider's handle for this upload. Required to finish or abandon it.
    upload_id: str
    part_size: int
    #: One signed URL per chunk, in order. The browser PUTs to each and keeps
    #: the identifier the response returns.
    part_urls: list[str]


class MediaStorage(ABC):
    @abstractmethod
    async def start_upload(
        self, *, key: str, content_type: str, byte_size: int
    ) -> UploadTicket:
        """Begin a multipart upload and sign a URL for every part."""

    @abstractmethod
    async def complete_upload(self, *, key: str, upload_id: str, etags: list[str]) -> None:
        """Assemble the parts into the finished object.

        `etags` must be in part order — the provider reassembles by position,
        not by content, so a shuffled list produces a corrupt file rather than
        an error.
        """

    @abstractmethod
    async def abort_upload(self, *, key: str, upload_id: str) -> None:
        """Discard an upload and its uploaded parts.

        Called when the caller knows an upload failed. Parts left behind by a
        browser that simply vanished are swept by the bucket's own lifecycle
        rule instead, since nothing here is around to notice.
        """

    @abstractmethod
    async def presign_download(
        self, *, key: str, expires_in: int = 300, as_filename: str | None = None
    ) -> str:
        """A URL that serves the object, then expires.

        `as_filename` asks the store to serve the object as an attachment
        under that name, which is what turns a link into a download.

        It belongs here rather than in the browser because neither half of
        the job can be done there. A cross-origin `download` attribute is
        ignored outright, so the anchor opens the photograph in a tab; and
        fetching the bytes to save a blob needs a CORS grant on the bucket,
        holds the whole file in the tab's memory, and so cannot survive a
        10 GB video. The store already knows how to say "attachment" — a
        signed response header costs nothing and the browser's own download
        manager streams the file to disk.

        Keyed on the object, not the asset, so the name travels separately:
        the same blob is referenced by every project that holds a copy of
        it, and each of those has its own filename.
        """

    @abstractmethod
    async def exists(self, *, key: str) -> int | None:
        """The object's size, or None if it was never finished.

        The confirmation step needs this. A client that starts an upload and
        never completes it would otherwise leave a row describing a file that
        does not exist, and a gallery full of broken images.
        """

    @abstractmethod
    async def delete(self, *, key: str) -> None:
        """Remove the object. Called only when its reference count reaches zero."""

    # ── server-side only ─────────────────────────────────────────────────
    # These two move bytes through this process, which the browser path
    # deliberately never does. They exist for the rendition worker: making a
    # watermarked preview means decoding the original, and there is no way to
    # do that without holding it. That worker is a scheduled job, not a
    # request handler, so nothing is waiting on it and no request times out.

    @abstractmethod
    async def write(self, *, key: str, data: bytes, content_type: str) -> None:
        """Store bytes the server already has, in one call.

        The multipart dance above exists so a browser can send a 40 GB film
        straight to the bucket without it passing through this process. That
        reasoning does not reach a profile picture: it is a few megabytes, the
        server wants to look at it anyway, and routing it directly costs a
        CORS policy, an exposed ETag header and two extra round trips — every
        one of which has broken avatar uploads in practice.
        """

    @abstractmethod
    async def read(self, *, key: str) -> bytes:
        """Fetch an object's bytes. For background processing, never a request."""

    @abstractmethod
    async def write(self, *, key: str, data: bytes, content_type: str) -> None:
        """Store bytes produced on the server, such as a generated rendition."""
