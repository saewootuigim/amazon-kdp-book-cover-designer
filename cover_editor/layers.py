"""The things on the canvas: placed pictures, and the fixed barcode placeholder.

A placed picture keeps two things apart. `Source` is the file — its path and
native size, plus a downscaled preview for drawing on screen. The export never
uses the preview; it goes back to the original file, so what lands in the PDF is
full resolution (and, for a PDF source, still vector).
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import pymupdf as fitz
from PIL import Image, ImageOps
from PySide6.QtCore import QRectF, QSizeF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QImage, QPainter, QPen
from PySide6.QtWidgets import QGraphicsItem, QStyleOptionGraphicsItem, QWidget

from .spec import PT_PER_IN

IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".jfif", ".webp", ".bmp", ".gif",
              ".tif", ".tiff", ".tga", ".ico")
PDF_EXTS = (".pdf",)
SUPPORTED_EXTS = PDF_EXTS + IMAGE_EXTS

# Longest side of the on-screen preview. Big enough to look sharp on a 4K
# screen at "fit" zoom, small enough that a dozen layers stay responsive.
PREVIEW_MAX_PX = 2400

# DPI assumed for an image's starting size. KDP asks for 300.
ASSUMED_DPI = 300

BARCODE_MESSAGE = ("Barcode placeholder — fixed in place and cannot be moved. "
                   "Amazon prints the real barcode here.")


def is_supported(path: str) -> bool:
    return path.lower().endswith(SUPPORTED_EXTS)


@dataclass
class Source:
    path: str
    kind: str  # "image" or "pdf"
    page: int  # 0-based; always 0 for images
    native_w: float  # pixels for an image, points for a PDF page
    native_h: float
    preview: QImage

    @property
    def name(self) -> str:
        base = os.path.basename(self.path)
        return f"{base} (page {self.page + 1})" if self.kind == "pdf" else base

    def natural_size_pt(self) -> tuple[float, float]:
        """The size it would have if placed 'as is': a PDF at its page size, an
        image at ASSUMED_DPI."""
        if self.kind == "pdf":
            return self.native_w, self.native_h
        k = PT_PER_IN / ASSUMED_DPI
        return self.native_w * k, self.native_h * k


def pdf_page_count(path: str) -> int:
    with fitz.open(path) as doc:
        return doc.page_count


def load_source(path: str, page: int = 0) -> Source:
    if path.lower().endswith(PDF_EXTS):
        return _load_pdf(path, page)
    return _load_image(path)


def _load_pdf(path: str, page: int) -> Source:
    with fitz.open(path) as doc:
        if not 0 <= page < doc.page_count:
            raise ValueError(f"{os.path.basename(path)} has no page {page + 1}.")
        pg = doc[page]
        w, h = pg.rect.width, pg.rect.height
        zoom = PREVIEW_MAX_PX / max(w, h)
        # alpha=True: a PDF page with no background is transparent in the
        # export too, so the preview must not invent a white one.
        pix = pg.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=True)
        img = QImage(pix.samples, pix.width, pix.height, pix.stride,
                     QImage.Format.Format_RGBA8888_Premultiplied).copy()
    return Source(path, "pdf", page, w, h, img)


def _load_image(path: str) -> Source:
    with Image.open(path) as im:
        im.seek(0)  # first frame of a GIF / multi-page TIFF
        im = ImageOps.exif_transpose(im)  # phone photos are often stored sideways
        native_w, native_h = im.size
        im.thumbnail((PREVIEW_MAX_PX, PREVIEW_MAX_PX), Image.Resampling.LANCZOS)
        im = im.convert("RGBA")
        data = im.tobytes("raw", "RGBA")
        img = QImage(data, im.width, im.height, 4 * im.width,
                     QImage.Format.Format_RGBA8888).copy()
    return Source(path, "image", 0, native_w, native_h, img)


class Layer(QGraphicsItem):
    """A placed picture. Its position is its top-left corner in scene points."""

    def __init__(self, source: Source):
        super().__init__()
        self.source = source
        w, h = source.natural_size_pt()
        self._w, self._h = w, h
        self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)  # the view handles input

    @property
    def name(self) -> str:
        return self.source.name

    def rect(self) -> QRectF:
        return QRectF(self.pos(), self.size())

    def size(self) -> QSizeF:
        return QSizeF(self._w, self._h)

    def set_rect(self, r: QRectF) -> None:
        r = r.normalized()
        if (r.width(), r.height()) != (self._w, self._h):
            self.prepareGeometryChange()
            self._w, self._h = r.width(), r.height()
        self.setPos(r.topLeft())

    def native_ratio(self) -> float:
        return self.source.native_w / self.source.native_h

    def effective_dpi(self) -> float | None:
        """Print resolution at the current size; None for a PDF (vector)."""
        if self.source.kind != "image":
            return None
        return min(self.source.native_w / (self._w / PT_PER_IN),
                   self.source.native_h / (self._h / PT_PER_IN))

    def boundingRect(self) -> QRectF:
        return QRectF(0, 0, self._w, self._h)

    def paint(self, painter: QPainter, option: QStyleOptionGraphicsItem,
              widget: QWidget | None = None) -> None:
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.drawImage(QRectF(0, 0, self._w, self._h), self.source.preview)


class BarcodeItem(QGraphicsItem):
    """KDP's barcode area. Always on top, never selectable, never movable."""

    Z = 1_000_000

    def __init__(self):
        super().__init__()
        self._rect = QRectF()
        self.setZValue(self.Z)
        self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self.setToolTip(BARCODE_MESSAGE)

    def set_rect(self, r: QRectF) -> None:
        self.prepareGeometryChange()
        self._rect = QRectF(r)

    def rect(self) -> QRectF:
        return QRectF(self._rect)

    def boundingRect(self) -> QRectF:
        return self._rect.adjusted(-1, -1, 1, 1)

    def paint(self, painter: QPainter, option: QStyleOptionGraphicsItem,
              widget: QWidget | None = None) -> None:
        r = self._rect
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(QPen(QColor("#888888"), 0))
        painter.setBrush(QColor("#ffffff"))
        painter.drawRect(r)

        # Fake bars across the top half.
        pad = r.height() * 0.08
        bars = QRectF(r.left() + pad, r.top() + pad, r.width() - 2 * pad, r.height() * 0.42)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(QColor("#9a9a9a")))
        widths = [2, 1, 1, 3, 1, 2, 1, 1, 2, 3, 1, 1, 2, 1, 3, 1, 2, 1, 1, 2, 1, 3, 2, 1]
        unit = bars.width() / (sum(widths) * 2)
        x = bars.left()
        for i, wdt in enumerate(widths):
            if i % 2 == 0:
                painter.drawRect(QRectF(x, bars.top(), wdt * unit, bars.height()))
            x += wdt * unit * 2
            if x >= bars.right():
                break

        painter.setPen(QPen(QColor("#444444")))
        text = QRectF(r.left() + pad, bars.bottom() + pad * 0.5,
                      r.width() - 2 * pad, r.bottom() - bars.bottom() - pad * 1.5)
        title = QFont("Segoe UI")
        title.setPixelSize(max(1, round(r.height() * 0.10)))
        title.setBold(True)
        painter.setFont(title)
        painter.drawText(text, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                         "BARCODE PLACEHOLDER")
        body = QFont("Segoe UI")
        body.setPixelSize(max(1, round(r.height() * 0.075)))
        painter.setFont(body)
        painter.drawText(text, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom
                         | Qt.TextFlag.TextWordWrap,
                         "Fixed — cannot be moved.\nAmazon places the real barcode here.")

