"""Authorise an upload — or discover there is nothing to upload.

The browser hashes a file before sending anything, which buys two things. The
obvious one is deduplication: a photograph already in the bucket is claimed in
milliseconds instead of pushed again. The less obvious one is that the key is
known *before* the bytes move, so a half-finished upload can never leave an
object nobody can name.
"""

from dataclasses import dataclass
from uuid import UUID

from app.core.exceptions import (
    EntityNotFoundError,
    PermissionDeniedError,
    ValidationError,
)
from app.domain.entities.asset import (
    Asset,
    AssetKind,
    StorageEvent,
    StorageEventKind,
    StoredObject,
    is_video,
)
from app.domain.entities.user import User
from app.domain.repositories.media_repository import MediaRepository
from app.domain.repositories.project_repository import ProjectRepository
from app.domain.services.media_storage import MediaStorage, UploadTicket

#: Stills and moving pictures. Video was refused outright until now, on the
#: reasoning that nothing could play it back — true of camera-native formats
#: and false of the delivered film, which is usually already H.264 and plays
#: in any browser. Refusing both to be safe about one meant a videography
#: studio could not upload its own work.
#:
#: What is still missing is transcoding, so a ProRes master uploads and stores
#: perfectly well and simply will not play in a browser. That is a limitation
#: to state in the interface, not a reason to reject the file.
ACCEPTED_PREFIXES = ("image/", "video/")

#: Generous ceilings that still reject a mistake. The largest medium-format
#: RAW in normal use is well under the first; a feature-length film in a
#: delivery codec is well under the second.
#:
#: Policy, not capability — multipart ceilings out around 100 GB. The number
#: to settle on is a storage-cost question, and that is tied to the pricing
#: decision that is still open (see ../CLAUDE.md §3).
MAX_IMAGE_BYTES = 2 * 1024 * 1024 * 1024
MAX_VIDEO_BYTES = 10 * 1024 * 1024 * 1024

_HEX = set("0123456789abcdef")


@dataclass
class UploadAuthorisation:
    """One of two outcomes, never both."""

    key: str
    #: Set when the bytes are new: the browser must upload them.
    ticket: UploadTicket | None = None
    #: Set when identical bytes were already stored: nothing to upload, the
    #: asset exists already.
    asset: Asset | None = None

    @property
    def already_stored(self) -> bool:
        return self.asset is not None


class RequestUpload:
    def __init__(
        self,
        projects: ProjectRepository,
        media: MediaRepository,
        storage: MediaStorage,
    ) -> None:
        self._projects = projects
        self._media = media
        self._storage = storage

    async def execute(
        self,
        *,
        project_id: UUID,
        actor: User,
        content_hash: str,
        filename: str,
        content_type: str,
        byte_size: int,
    ) -> UploadAuthorisation:
        project = await self._projects.get_by_id(project_id)
        if project is None:
            raise EntityNotFoundError("Project not found")
        if not project.is_managed_by(actor):
            raise PermissionDeniedError("You cannot upload to this project.")

        content_hash = content_hash.strip().lower()
        if len(content_hash) != 64 or not set(content_hash) <= _HEX:
            # Checked because the hash becomes the object key. A malformed one
            # would be stored happily and never found again.
            raise ValidationError("That is not a SHA-256 hash.")
        if byte_size <= 0:
            raise ValidationError("A file needs a size.")
        if not content_type.startswith(ACCEPTED_PREFIXES):
            raise ValidationError(
                f"{content_type} is not a photograph or a video, so there is "
                "nothing we could show a client."
            )

        # Checked after the type, so an oversized video is measured against
        # the video ceiling rather than told it is too big for a photograph.
        ceiling = MAX_VIDEO_BYTES if is_video(content_type) else MAX_IMAGE_BYTES
        if byte_size > ceiling:
            raise ValidationError(
                f"That file is larger than the {ceiling // 1024**3} GB limit."
            )

        candidate = StoredObject(
            content_hash=content_hash, byte_size=byte_size, content_type=content_type
        )

        existing = await self._media.get_object(content_hash)
        if existing is not None:
            # Identical bytes are already held. Claim them for this project and
            # the upload is finished before it started.
            return UploadAuthorisation(
                key=existing.key,
                asset=await self._claim(project, actor, existing, filename),
            )

        return UploadAuthorisation(
            key=candidate.key,
            ticket=await self._storage.start_upload(
                key=candidate.key, content_type=content_type, byte_size=byte_size
            ),
        )

    async def _claim(
        self, project, actor: User, blob: StoredObject, filename: str
    ) -> Asset:
        """Point a new asset at bytes we already hold."""
        asset = Asset(
            project_id=project.id,
            content_hash=blob.content_hash,
            kind=AssetKind.ORIGINAL,
            filename=filename,
            uploaded_by=actor.id,
        )
        # Charged to whoever owns the project, not whoever clicked upload — an
        # admin helping a creator must not consume the admin's allowance.
        return await self._media.record_asset(
            blob,
            asset,
            StorageEvent(
                account_id=project.creator_id or actor.id,
                asset_id=asset.id,
                kind=StorageEventKind.ADDED,
                byte_size=blob.byte_size,
            ),
        )
