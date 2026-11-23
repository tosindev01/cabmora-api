"""Make the files a client is allowed to look at.

There is no job queue. `kind=ORIGINAL AND renditions_ready_at IS NULL` is the
queue — the asset table already knows what is outstanding, and a second table
to keep in step with it would be one more thing that can disagree. It is also
inspectable: the pending work is visible in the same place as the photographs.

Never inside the upload request: resizing a 40-megapixel RAW takes seconds,
the source has to be pulled back out of R2 to do it, and an admin dropping two
hundred files should wait for none of that.

Two ways in, and the difference matters. `execute_one` is fired the instant an
upload is confirmed, after the response has gone — so a photograph is
viewable a second or two later rather than whenever a timer next looks.
`execute` sweeps whatever is still outstanding and runs on a schedule; it is
the safety net for a container that restarted mid-render, not the normal path.
It was the normal path once, and a sweep that silently stopped running meant
photographs that were uploaded, released, and permanently invisible.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

from app.domain.entities.asset import (
    Asset,
    AssetKind,
    StorageEvent,
    StorageEventKind,
    StoredObject,
    is_video,
)
from app.domain.repositories.media_repository import MediaRepository
from app.domain.repositories.project_repository import ProjectRepository
from app.domain.services.image_processor import ImageProcessor
from app.domain.services.media_storage import MediaStorage

logger = logging.getLogger(__name__)

#: What the tiled mark says. Not per-project: a watermark is a statement of
#: whose work this is, and the studio's name is the answer on every frame.
WATERMARK_TEXT = "CABMORA"

#: A ceiling per run, so one enormous wedding cannot monopolise the worker and
#: starve every other project of its previews for an hour.
BATCH = 20


@dataclass
class RenditionReport:
    processed: int
    failed: int


class GenerateRenditions:
    def __init__(
        self,
        media: MediaRepository,
        projects: ProjectRepository,
        storage: MediaStorage,
        images: ImageProcessor,
    ) -> None:
        self._media = media
        self._projects = projects
        self._storage = storage
        self._images = images

    async def execute(self, limit: int = BATCH) -> RenditionReport:
        """Sweep everything outstanding. The safety net, on a schedule."""
        pending = await self._media.list_awaiting_renditions(limit=limit)
        processed = failed = 0
        for original in pending:
            if await self._attempt(original):
                processed += 1
            else:
                failed += 1
        return RenditionReport(processed=processed, failed=failed)

    async def execute_one(self, asset_id: UUID) -> bool:
        """Render one photograph now, called the moment its upload lands.

        Re-read rather than handed in, and skipped when the work is already
        done: the scheduled sweep may have reached this asset first, and
        rendering twice would write a second set of storage events for bytes
        that were only stored once. It narrows that window rather than closing
        it — two renders starting in the same instant would still both go —
        but the loser overwrites identical output, and the cost is a
        duplicated usage row rather than a wrong photograph.
        """
        original = await self._media.get_asset(asset_id)
        if original is None or not original.awaiting_renditions:
            return False
        return await self._attempt(original)

    async def _attempt(self, original: Asset) -> bool:
        """Render one asset, absorbing its failure. True when it worked."""
        try:
            await self._render(original)
            return True
        except Exception as exc:  # noqa: BLE001
            # One unreadable file must not stop the rest of the wedding.
            original.rendition_failed(repr(exc))
            await self._media.update_asset(original)

            if original.renditions_abandoned:
                # Said once, loudly, and then never again: this asset drops
                # out of the queue, so an admin sees a photograph that needs
                # attention rather than an alert every few minutes for the
                # rest of the system's life.
                logger.error(
                    "[renditions] %s (%s) failed %d times — giving up: %r",
                    original.id, original.filename,
                    original.rendition_attempts, exc,
                )
            else:
                logger.warning(
                    "[renditions] %s (%s) failed, attempt %d: %r",
                    original.id, original.filename,
                    original.rendition_attempts, exc,
                )
            return False

    async def _render(self, original: Asset) -> None:
        blob = await self._media.get_object(original.content_hash)
        if blob is None:
            raise RuntimeError("the stored object is missing")

        if is_video(blob.content_type):
            # Nothing to make, and nothing to read. Two reasons to return
            # before touching the bytes: the image library cannot decode a
            # video and would fail on every attempt until the asset was
            # abandoned, and `storage.read` pulls the whole file into this
            # process — fine for a 40 MB photograph, not for a 6 GB film.
            #
            # Marked ready all the same. `renditions_ready` is the gallery's
            # "is there something safe to show", and for a video the answer is
            # settled the moment it lands: there is one file and the payment
            # gate decides who gets it. Leaving it false would hold the video
            # in a queue that will never produce anything.
            original.renditions_ready_at = datetime.now(timezone.utc)
            await self._media.update_asset(original)
            logger.info(
                "[renditions] %s is video (%s) — no renditions to make",
                original.id, original.filename,
            )
            return

        source = await self._storage.read(key=blob.key)

        project = await self._projects.get_by_id(original.project_id)
        # Charged to whoever owns the project — the same account the original
        # was charged to, so a creator's usage adds up.
        account_id = (project.creator_id if project else None) or original.uploaded_by

        for kind, rendition in (
            (AssetKind.PREVIEW, self._images.preview(source, watermark=WATERMARK_TEXT)),
            (AssetKind.THUMBNAIL, self._images.thumbnail(source, watermark=WATERMARK_TEXT)),
        ):
            await self._store(original, kind, rendition, account_id)

        original.renditions_ready_at = datetime.now(timezone.utc)
        await self._media.update_asset(original)
        logger.info("[renditions] %s ready (%s)", original.id, original.filename)

    async def _store(self, original: Asset, kind, rendition, account_id) -> None:
        import hashlib

        digest = hashlib.sha256(rendition.data).hexdigest()
        blob = StoredObject(
            content_hash=digest,
            byte_size=rendition.byte_size,
            content_type=rendition.content_type,
        )

        # Renditions are content-addressed like everything else, so two
        # identical originals produce one stored preview between them.
        if await self._media.get_object(digest) is None:
            await self._storage.write(
                key=blob.key,
                data=rendition.data,
                content_type=rendition.content_type,
            )

        derived = Asset(
            project_id=original.project_id,
            content_hash=digest,
            kind=kind,
            filename=original.filename,
            uploaded_by=original.uploaded_by,
            # Lineage, so removing an original can find what it spawned.
            derived_from=original.id,
            # A rendition is never "pending" — it is the thing that was pending.
            renditions_ready_at=datetime.now(timezone.utc),
            # It inherits nothing about release: whether a client may see the
            # photograph is a decision about the original.
        )
        await self._media.record_asset(
            blob,
            derived,
            StorageEvent(
                account_id=account_id,
                asset_id=derived.id,
                kind=StorageEventKind.ADDED,
                byte_size=rendition.byte_size,
            ),
        )
