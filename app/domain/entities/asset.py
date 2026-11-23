"""Stored media, and the two records that cannot be retrofitted.

Two decisions here are irreversible once real bytes exist, which is why they
are made before a single upload rather than when they first hurt:

**Objects are keyed by content hash, not by path.** `projects/<id>/<filename>`
is the obvious scheme and the wrong one: the same photograph sent by two
clients, or re-uploaded after a rename, becomes two stored copies, and there is
no way to notice. Changing the key later is a migration across every byte held.

**Storage is a log, not a counter.** A `used_bytes` column answers "how much
now" and destroys "how much then" forever. No future pricing model can be
backfilled against a number, so the deltas are kept instead and the total is
derived from them.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from uuid import UUID, uuid4


#: Attempts before the worker gives up on a file and leaves it for a person.
#: Five is generous for anything transient and short enough that a bad upload
#: stops being noise within half an hour.
MAX_RENDITION_ATTEMPTS = 5


def is_video(content_type: str) -> bool:
    """Whether a stored file is moving pictures rather than a still.

    A function on the media type rather than a column: the type is already
    recorded on the blob, and a second field saying the same thing is a second
    field that can disagree with it.

    Note what this cannot tell you. `video/quicktime` is a .mov, which may be
    H.264 that any browser plays or ProRes that none of them do — the
    container is in the MIME type, the codec is not. Until there is
    transcoding, playback is best effort and the honest place to say so is the
    interface, not here.
    """
    return content_type.startswith("video/")


class AssetKind(str, Enum):
    #: The file the client gave us, byte for byte. RAWs are irreplaceable and
    #: they are the product — this is never recompressed, watermarked or
    #: resized. Every other kind is derived from one of these.
    ORIGINAL = "original"
    #: Watermarked, downscaled, and what the customer actually reviews.
    PREVIEW = "preview"
    #: Grid-sized. Cheap enough to load a hundred at once.
    THUMBNAIL = "thumbnail"


@dataclass
class StoredObject:
    """One blob in the bucket, and how many assets point at it.

    Separate from `Asset` because the mapping is many-to-one: two projects can
    reference identical bytes. Without the count, deleting one project's copy
    would pull the file out from under the other's.
    """

    #: SHA-256 of the file's contents, lowercase hex. This is the object key.
    content_hash: str
    byte_size: int
    content_type: str
    reference_count: int = 1
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def key(self) -> str:
        """Where this lives in the bucket.

        Sharded on the first four hex characters. A flat prefix with a hundred
        thousand siblings makes listing and lifecycle rules slow, and the shard
        costs nothing to adopt now and a migration to adopt later.
        """
        return f"assets/{self.content_hash[:2]}/{self.content_hash[2:4]}/{self.content_hash}"

    def claimed(self) -> "StoredObject":
        """Another asset now points here."""
        self.reference_count += 1
        return self

    def released(self) -> "StoredObject":
        """One fewer asset points here. At zero the blob can be collected."""
        self.reference_count = max(0, self.reference_count - 1)
        return self

    @property
    def is_orphaned(self) -> bool:
        return self.reference_count == 0


@dataclass
class Asset:
    """A file as it appears inside one project."""

    project_id: UUID
    content_hash: str
    kind: AssetKind
    #: The name the client's machine gave it. Display only — never a key, or
    #: two people's `IMG_2856.jpg` would collide.
    filename: str
    uploaded_by: UUID
    #: The ORIGINAL this was derived from; None when this *is* an original.
    #: Lineage, so removing an original can find the renditions it spawned.
    derived_from: UUID | None = None
    #: Set when the rendition pipeline has produced this asset's derivatives.
    #: An original with no renditions yet is uploaded but not yet viewable.
    renditions_ready_at: datetime | None = None
    #: When the client was allowed to see this photograph. None means never —
    #: the deliberate default. A shoot contains frames nobody should show: the
    #: blinks, the test exposures, the ones the couple would hate. Uploading
    #: everything and choosing later is how photographers actually work, so
    #: withheld has to be the starting state rather than something to remember.
    released_at: datetime | None = None
    #: How many times the rendition worker has tried and failed on this file,
    #: and why it failed last. Counted because the queue is a query rather
    #: than a jobs table: without a limit, one corrupt upload is retried every
    #: few minutes for the lifetime of the system.
    rendition_attempts: int = 0
    rendition_error: str | None = None
    #: The photograph this one replaces, when it was uploaded as a correction.
    #:
    #: Recorded on the replacement rather than the replaced, so there is one
    #: writer per fact and a chain of corrections reads in the order it
    #: happened. The old frame is never deleted — a client asked for a change,
    #: not for the evidence to disappear, and the comments they left still
    #: hang off it.
    supersedes: UUID | None = None
    #: Which part of the shoot this is filed under. None means unfiled, which
    #: is the starting state and a perfectly good place to stay — a small job
    #: does not need folders, and nothing should force one.
    #:
    #: Organisation only. This never affects `released_at`: filing a
    #: photograph and showing it to a client are separate decisions.
    folder_id: UUID | None = None
    id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def is_original(self) -> bool:
        return self.kind is AssetKind.ORIGINAL

    @property
    def is_released(self) -> bool:
        return self.released_at is not None

    def replaces(self, previous: "Asset") -> None:
        """Take the place of an earlier frame.

        The release state is inherited deliberately. If the client has already
        been shown the photograph they complained about, the corrected version
        must not need a second, separate gesture before they can see it —
        forgetting that would leave them looking at nothing where their photo
        used to be.
        """
        self.supersedes = previous.id
        self.released_at = previous.released_at

    def rendition_failed(self, reason: str) -> None:
        """Record an attempt that did not work.

        The reason is kept because "failed" and "is not an image file" call
        for completely different actions from whoever looks.
        """
        self.rendition_attempts += 1
        # Truncated: a stack trace in a column nobody can widen helps no one,
        # and the log has the whole thing.
        self.rendition_error = reason[:500]

    @property
    def renditions_abandoned(self) -> bool:
        """Tried enough times that trying again is not the answer.

        Transient failures — a timeout, a bad moment for the storage provider
        — clear within a couple of attempts. Past that it is the file, and
        retrying forever turns one corrupt upload into an alert every few
        minutes, indefinitely, which is how people learn to ignore alerts.
        """
        return self.rendition_attempts >= MAX_RENDITION_ATTEMPTS

    @property
    def awaiting_renditions(self) -> bool:
        """An original the worker has not processed yet.

        The gallery needs this: showing an original's own bytes because its
        watermarked preview does not exist yet would hand over exactly the file
        the watermark exists to protect.
        """
        return self.is_original and self.renditions_ready_at is None


class StorageEventKind(str, Enum):
    ADDED = "added"
    REMOVED = "removed"


@dataclass
class StorageEvent:
    """One movement of bytes, append-only.

    Never updated and never deleted, including when the asset is. A creator's
    usage at any past date is a sum over these rows, which is the only reason
    a pricing change can ever be modelled against real history.
    """

    #: Whose allowance this counts against — the creator who owns the project,
    #: not whoever clicked upload.
    account_id: UUID
    asset_id: UUID
    kind: StorageEventKind
    #: Always positive. `kind` carries the direction, so a corrupted sign
    #: cannot silently credit somebody storage they never released.
    byte_size: int
    id: UUID = field(default_factory=uuid4)
    occurred_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def signed_bytes(self) -> int:
        """The delta to apply when summing a balance."""
        return self.byte_size if self.kind is StorageEventKind.ADDED else -self.byte_size
