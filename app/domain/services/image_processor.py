"""Turning an original into what a client is allowed to see.

A port rather than a direct Pillow call, for the same reason email and storage
are ports: the use case that decides *when* renditions are made should not
know how a JPEG is encoded, and the rule it enforces — that originals are
never modified — is worth stating in an interface rather than trusting to
whoever edits the implementation next.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass

#: The long edge of what a client reviews. Big enough to judge focus and
#: expression, small enough that it is not a usable substitute for the file
#: they have not paid for.
PREVIEW_EDGE = 2048

#: Grid-sized. A hundred of these load without thinking about it.
THUMBNAIL_EDGE = 600


@dataclass(frozen=True)
class Rendition:
    data: bytes
    content_type: str
    byte_size: int


class ImageProcessor(ABC):
    @abstractmethod
    def avatar(self, original: bytes, *, edge: int) -> Rendition:
        """A square profile picture, re-encoded and stripped of metadata.

        No watermark: this is somebody's face on their own account, not a
        deliverable being protected. Re-encoding is the point rather than a
        side effect — a phone photograph carries EXIF, and EXIF carries the
        GPS coordinates of wherever it was taken. Storing that because
        somebody chose a picture of themselves is not a trade anybody agreed
        to.
        """

    @abstractmethod
    def preview(self, original: bytes, *, watermark: str) -> Rendition:
        """A downscaled, watermarked copy for review."""

    @abstractmethod
    def thumbnail(self, original: bytes, *, watermark: str) -> Rendition:
        """A grid-sized copy. Also watermarked — a thumbnail is still the
        client's first sight of the work, and an unmarked one is a small
        unmarked photograph rather than a safe one."""
