"""Write the cover as a one-page PDF, exactly the full cover size.

Each picture goes back to its original file, not the on-screen preview:
JPEG and PNG files are embedded byte-for-byte where possible, other formats are
converted losslessly to PNG, and a placed PDF page is drawn as vector content.
A text box is painted by Qt into a one-page PDF of its own, as outlines, and
placed the same way.
Whatever hangs past the page edge is clipped by the page itself.
"""

from __future__ import annotations

import io
import math
import os
import tempfile

import pymupdf as fitz
from PIL import Image, ImageOps
from PySide6.QtCore import QBuffer, QIODevice, QMarginsF, QSizeF
from PySide6.QtGui import QPageSize, QPainter, QPdfWriter

from .layers import Layer, TextLayer
from .spec import PT_PER_IN, CoverSpec

EXIF_ORIENTATION = 0x0112


def _image_stream(path: str) -> bytes:
    with Image.open(path) as im:
        rotated = im.getexif().get(EXIF_ORIENTATION, 1) not in (1, None)
        if not rotated and (
            (im.format == "JPEG" and im.mode in ("RGB", "L", "CMYK"))
            or (im.format == "PNG" and not getattr(im, "is_animated", False))
        ):
            with open(path, "rb") as f:
                return f.read()  # untouched: no recompression
        im.seek(0)
        im = ImageOps.exif_transpose(im)
        has_alpha = im.mode in ("RGBA", "LA", "PA") or "transparency" in im.info
        im = im.convert("RGBA" if has_alpha else "RGB")
        buf = io.BytesIO()
        im.save(buf, format="PNG", optimize=False)
        return buf.getvalue()


def _text_pdf(layer: TextLayer) -> fitz.Document:
    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    writer = QPdfWriter(buf)
    writer.setResolution(72)  # one unit = one point, as in the scene
    # QPageSize keeps whole points, so round up; show_pdf_page clips to the exact box.
    size = QSizeF(math.ceil(layer.size().width()), math.ceil(layer.size().height()))
    writer.setPageSize(QPageSize(size, QPageSize.Unit.Point, "", QPageSize.SizeMatchPolicy.ExactMatch))
    writer.setPageMargins(QMarginsF(0, 0, 0, 0))
    painter = QPainter(writer)
    layer.paint_content(painter)
    painter.end()
    return fitz.open("pdf", bytes(buf.data()))


def _draw_barcode(page: fitz.Page, spec: CoverSpec) -> None:
    b = spec.barcode().pt()
    rect = fitz.Rect(b.x, b.y, b.right, b.bottom)
    page.draw_rect(rect, color=(0.53, 0.53, 0.53), fill=(1, 1, 1), width=0.5)
    page.insert_textbox(rect + (6, rect.height * 0.3, -6, -4),
                        "BARCODE PLACEHOLDER\nAmazon places the real barcode here.",
                        fontsize=7, fontname="helv", color=(0.27, 0.27, 0.27), align=1)


def export_pdf(path: str, spec: CoverSpec, layers: list[Layer], include_barcode: bool = False) -> None:
    width, height = spec.full_width * PT_PER_IN, spec.full_height * PT_PER_IN
    out = fitz.open()
    page = out.new_page(width=width, height=height)
    sources: dict[str, fitz.Document] = {}
    try:
        for layer in layers:  # bottom to top
            r = layer.rect()
            rect = fitz.Rect(r.left(), r.top(), r.right(), r.bottom())
            if rect.is_empty or not rect.intersects(page.rect):
                continue  # entirely off the page
            if isinstance(layer, TextLayer):
                with _text_pdf(layer) as doc:
                    page.show_pdf_page(rect, doc, 0, keep_proportion=False,
                                       clip=fitz.Rect(0, 0, r.width(), r.height()))
                continue
            src = layer.source
            if src.kind == "pdf":
                if src.path not in sources:
                    sources[src.path] = fitz.open(src.path)
                page.show_pdf_page(rect, sources[src.path], src.page, keep_proportion=False)
            else:
                page.insert_image(rect, stream=_image_stream(src.path), keep_proportion=False)

        if include_barcode:
            _draw_barcode(page, spec)

        out.set_metadata({"title": "Book cover", "creator": "Book Cover Editor",
                          "producer": f"PyMuPDF {fitz.VersionBind}"})
        # Write beside the target, then swap it in, so a failed save never
        # leaves half a file — and saving over a PDF that is also a layer works.
        folder = os.path.dirname(os.path.abspath(path))
        fd, tmp = tempfile.mkstemp(suffix=".pdf", dir=folder)
        os.close(fd)
        try:
            out.save(tmp, garbage=3, deflate=True)
        except Exception:
            os.remove(tmp)
            raise
    finally:
        out.close()
        for doc in sources.values():
            doc.close()
    os.replace(tmp, path)
