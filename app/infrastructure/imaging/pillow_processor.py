"""Renditions, made with Pillow.

Three details here are the difference between something that works and
something photographers complain about:

**Orientation.** A camera writes the picture as the sensor saw it and records
which way up it was in EXIF. Ignore that and roughly half of all portrait
shots come out sideways in the preview while the original looks perfect — a
bug nobody who writes code notices and everybody who takes pictures does.

**Colour mode.** Scans and print-bound files arrive as CMYK, screenshots as
RGBA with transparency. Saving either straight to JPEG raises or produces a
black background, so both are converted first.

**The original is never touched.** Everything here works on a decoded copy in
memory and returns new bytes. RAWs are irreplaceable, and they are the product.
"""

import io
from math import ceil

from PIL import Image, ImageDraw, ImageFont, ImageOps

from app.domain.services.image_processor import (
    PREVIEW_EDGE,
    THUMBNAIL_EDGE,
    ImageProcessor,
    Rendition,
)

#: Visible enough to deter, faint enough to judge the photograph through.
_WATERMARK_ALPHA = 58

#: Tilted so the text crosses image features rather than sitting along them,
#: which makes it far harder to clone out.
_WATERMARK_ANGLE = 30

#: Quality chosen against file size, not sharpness: a preview is for judging
#: composition, and 85 is where JPEG stops paying for itself.
_JPEG_QUALITY = 85


def _decoded(original: bytes) -> Image.Image:
    image = Image.open(io.BytesIO(original))
    # Must happen before any resize, or the rotation is applied to a
    # differently-shaped picture.
    image = ImageOps.exif_transpose(image)
    if image.mode in {"CMYK", "P", "LA", "RGBA"}:
        image = image.convert("RGB")
    elif image.mode != "RGB":
        image = image.convert("RGB")
    return image


def _font(size: int) -> ImageFont.ImageFont:
    """A scalable default, so this works in a bare container.

    Railway's image carries no fonts of its own. Pillow's built-in face is
    plain, which suits a watermark — it is meant to be read, not admired.
    """
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # pragma: no cover — very old Pillow
        return ImageFont.load_default()


def _tiled_watermark(image: Image.Image, text: str) -> Image.Image:
    """Stamp `text` repeatedly across the picture, on the diagonal."""
    width, height = image.size
    # Scaled to the picture so a thumbnail and a 2K preview look like the same
    # treatment rather than two different ones.
    size = max(14, width // 22)
    font = _font(size)

    probe = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    box = probe.textbbox((0, 0), text, font=font)
    text_width, text_height = box[2] - box[0], box[3] - box[1]

    step_x = text_width + size * 2
    step_y = text_height + size * 3

    # Drawn on an oversized layer, then rotated and cropped back, so the tiling
    # still covers the corners after the rotation.
    diagonal = ceil((width**2 + height**2) ** 0.5)
    layer = Image.new("RGBA", (diagonal, diagonal), (255, 255, 255, 0))
    pen = ImageDraw.Draw(layer)
    for y in range(0, diagonal, step_y):
        # Every other row offset, so the marks do not form clean columns a
        # crop could slip between.
        offset = (step_x // 2) if (y // step_y) % 2 else 0
        for x in range(-step_x, diagonal, step_x):
            pen.text((x + offset, y), text, font=font,
                     fill=(255, 255, 255, _WATERMARK_ALPHA))

    rotated = layer.rotate(_WATERMARK_ANGLE, resample=Image.BICUBIC)
    left, top = (diagonal - width) // 2, (diagonal - height) // 2
    cropped = rotated.crop((left, top, left + width, top + height))

    marked = image.convert("RGBA")
    marked.alpha_composite(cropped)
    return marked.convert("RGB")


def _encode(image: Image.Image) -> Rendition:
    buffer = io.BytesIO()
    # `optimize` costs a little CPU once and saves bytes on every view.
    image.save(buffer, format="JPEG", quality=_JPEG_QUALITY, optimize=True)
    data = buffer.getvalue()
    return Rendition(data=data, content_type="image/jpeg", byte_size=len(data))


class PillowImageProcessor(ImageProcessor):
    def _render(self, original: bytes, edge: int, watermark: str) -> Rendition:
        image = _decoded(original)
        # `thumbnail` only ever shrinks, so a small original is left alone
        # rather than upscaled into softness.
        image.thumbnail((edge, edge), Image.LANCZOS)
        return _encode(_tiled_watermark(image, watermark))

    def avatar(self, original: bytes, *, edge: int) -> Rendition:
        image = _decoded(original)
        # Cover-cropped to a square rather than squashed: an avatar is shown
        # in a circle everywhere in this product, and a letterboxed face in a
        # circle is a face with its chin cut off.
        image = ImageOps.fit(image, (edge, edge), method=Image.LANCZOS)
        # `_encode` writes a fresh JPEG from pixels alone, so nothing of the
        # original file's metadata survives.
        return _encode(image)

    def preview(self, original: bytes, *, watermark: str) -> Rendition:
        return self._render(original, PREVIEW_EDGE, watermark)

    def thumbnail(self, original: bytes, *, watermark: str) -> Rendition:
        return self._render(original, THUMBNAIL_EDGE, watermark)
