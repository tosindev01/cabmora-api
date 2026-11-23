"""Put a profile picture in the bucket, in one request.

Bytes do pass through the API here, and that is a deliberate departure. The
rule they are exempt from exists for 40 GB films: Railway egress billed twice,
a whole file held in this container, a request timing out mid-upload. None of
it describes an eight-megabyte photograph.

What the direct-to-bucket path did cost was a CORS policy on the bucket, an
exposed ETag header that browsers hide by default, and two extra round trips —
and every one of those broke avatar uploads in practice, silently. Consistency
with the media pipeline was chosen once over simplicity; it turned out to be
the more expensive of the two.

Holding the bytes also buys things the old path could not do at all: the file
is decoded to prove it is an image rather than trusted to say so, resized
instead of stored at phone resolution, and re-encoded — which strips the EXIF
block, and with it the GPS coordinates of wherever the photograph was taken.
"""

import asyncio
import hashlib

from app.core.exceptions import ValidationError
from app.domain.entities.user import User
from app.domain.repositories.user_repository import UserRepository
from app.domain.services.image_processor import ImageProcessor
from app.domain.services.media_storage import MediaStorage

#: A profile picture, not a deliverable. Generous enough for a phone photo
#: straight from the camera roll, small enough that nobody uploads a RAW.
MAX_BYTES = 8 * 1024 * 1024

#: Stored at 512px square. Shown at 36–64px across the product, so this is
#: generous for a retina screen and still a fraction of what a phone sends.
AVATAR_EDGE = 512

ALLOWED_TYPES = frozenset({"image/jpeg", "image/png", "image/webp"})


def avatar_key(user_id, content_hash: str) -> str:
    """Content-addressed, under the owner.

    The hash means re-uploading the same picture reuses the same object, and
    the user prefix means a key cannot be guessed from an email address.
    """
    return f"avatars/{user_id}/{content_hash}"


class ChangeAvatar:
    """Take the picture, make it safe to serve, store it, point the account at it."""

    def __init__(
        self, users: UserRepository, storage: MediaStorage, images: ImageProcessor
    ) -> None:
        self._users = users
        self._storage = storage
        self._images = images

    async def execute(self, *, actor: User, data: bytes, content_type: str) -> User:
        if content_type not in ALLOWED_TYPES:
            raise ValidationError(
                "A profile picture has to be a JPEG, PNG or WebP image."
            )
        if not data:
            raise ValidationError("That file is empty.")
        if len(data) > MAX_BYTES:
            raise ValidationError(
                f"A profile picture has to be under {MAX_BYTES // (1024 * 1024)} MB."
            )

        try:
            # Decoding is the real check. A content type is a claim the browser
            # makes, and `image/jpeg` on a zip file is a claim it will happily
            # make — the only way to know this is a photograph is to look.
            rendition = await asyncio.to_thread(
                self._images.avatar, data, edge=AVATAR_EDGE
            )
        except Exception as exc:  # noqa: BLE001
            raise ValidationError(
                "That file could not be read as an image. Try a JPEG or PNG."
            ) from exc

        # Keyed by the hash of what is stored, not of what arrived. Two people
        # sending the same photograph through different phones produce
        # different uploads and identical renditions, and the key should follow
        # the bytes in the bucket.
        digest = hashlib.sha256(rendition.data).hexdigest()
        key = avatar_key(actor.id, digest)
        await self._storage.write(
            key=key, data=rendition.data, content_type=rendition.content_type
        )

        previous = actor.avatar_key
        actor.avatar_key = key
        saved = await self._users.save_profile(actor)

        # The old picture is this account's alone — the key carries the user id
        # — so nothing else can be pointing at it. Re-uploading the same image
        # produces the same key, which is why this compares before deleting.
        if previous and previous != key:
            await self._storage.delete(key=previous)

        return saved
