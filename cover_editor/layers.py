"""The things on the canvas: placed pictures, text boxes, and the fixed barcode placeholder.

A placed picture keeps two things apart. `Source` is the file — its path and
native size, plus a downscaled preview for drawing on screen. The export never
uses the preview; it goes back to the original file, so what lands in the PDF is
full resolution (and, for a PDF source, still vector).

A text box is drawn as outlines (a QPainterPath) rather than as text, both on
screen and in the PDF, so the export needs no font files and looks exactly
like the screen.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, fields

import pymupdf as fitz
from PIL import Image, ImageOps
from PySide6.QtCore import QPointF, QRectF, QSizeF, Qt
from PySide6.QtGui import (QBrush, QColor, QFont, QFontMetricsF, QImage, QPainter, QPainterPath,
                           QPen, QTextLayout, QTransform)
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

# Text is laid out at this pixel size and then scaled down to its point size.
# Pixel sizes don't depend on the screen's DPI, so screen and PDF agree.
LAYOUT_PX = 1000
TEXT_PAD_PT = 3  # gap between the box edge and the text, plus the outline

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

    def __init__(self, source: Source | None):
        super().__init__()
        self.source = source  # None for a TextLayer
        self._w, self._h = source.natural_size_pt() if source else (PT_PER_IN, PT_PER_IN)
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


@dataclass
class TextStyle:
    text: str = "Your text"
    family: str = "Georgia"
    size: float = 36.0  # points
    bold: bool = False
    italic: bool = False
    align: str = "left"  # "left" | "center" | "right"
    color: str = "#ffffff"
    background: bool = False  # False: transparent
    background_color: str = "#ffffff"
    outline: bool = True
    outline_color: str = "#000000"
    outline_width: float = 1.0  # points, visible outside the letters
    rotation: int = 0  # degrees counterclockwise: 0, 90, 180 or 270

    @property
    def sideways(self) -> bool:
        return self.rotation in (90, 270)

    def to_dict(self) -> dict:
        return {f.name: getattr(self, f.name) for f in fields(self)}

    @classmethod
    def from_dict(cls, d: dict) -> "TextStyle":
        names = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in d.items() if k in names})

    def padding(self) -> float:
        return TEXT_PAD_PT + (self.outline_width if self.outline else 0)


def text_path(style: TextStyle, width: float) -> tuple[QPainterPath, float]:
    """The text wrapped to a box `width` points wide, as a path in box
    coordinates, and the box height the text needs."""
    font = QFont(style.family)
    font.setPixelSize(LAYOUT_PX)
    font.setBold(style.bold)
    font.setItalic(style.italic)
    fm = QFontMetricsF(font)
    k = style.size / LAYOUT_PX
    pad = style.padding()
    wrap = max(1.0, (width - 2 * pad) / k)
    path = QPainterPath()
    y = 0.0
    for para in style.text.split("\n"):
        layout = QTextLayout(para, font)
        layout.beginLayout()
        while (line := layout.createLine()).isValid():
            line.setLineWidth(wrap)
        layout.endLayout()
        for i in range(max(1, layout.lineCount())):
            if i < layout.lineCount():
                line = layout.lineAt(i)
                s = para[line.textStart():line.textStart() + line.textLength()].rstrip()
                x = {"left": 0.0, "center": 0.5, "right": 1.0}.get(style.align, 0.5) * (
                    wrap - fm.horizontalAdvance(s))
                path.addText(QPointF(x, y + fm.ascent()), font, s)
            y += fm.lineSpacing()
    to_box = QTransform().translate(pad, pad).scale(k, k)
    return to_box.map(path), y * k + 2 * pad


def paint_text(painter: QPainter, style: TextStyle, w: float, h: float, path: QPainterPath) -> None:
    """Shared by the screen and the PDF export."""
    box = QRectF(0, 0, w, h)
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    if style.background:
        painter.fillRect(box, QColor(style.background_color))
    painter.setClipRect(box)
    if style.outline and style.outline_width > 0:
        # Twice as wide, half of it hidden under the fill: the outline sits outside the letters.
        pen = QPen(QColor(style.outline_color), style.outline_width * 2, Qt.PenStyle.SolidLine,
                   Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
        painter.strokePath(path, pen)
    painter.fillPath(path, QColor(style.color))
    painter.restore()


class TextLayer(Layer):
    """A text box. The text wraps to the box's width and is cut off at its edges.

    Its rect is the box as it sits on the cover. Turned sideways, the text runs
    along the box's height, so its "width" is the rect's height.
    """

    def __init__(self, style: TextStyle | None = None, width: float = 4 * PT_PER_IN):
        super().__init__(None)
        self.style = style or TextStyle()
        self._path: QPainterPath | None = None
        self._path_key = None
        self._w = width
        self._h = self.content_height()

    @property
    def name(self) -> str:
        first = self.style.text.strip().split("\n")[0].strip()
        return f"Text: {first[:30] + '…' if len(first) > 30 else first}" if first else "Text (empty)"

    def set_style(self, style: TextStyle) -> None:
        self.style = style
        self.update()

    def text_size(self) -> tuple[float, float]:
        """The box's width and height as the text sees them, before rotation."""
        return (self._h, self._w) if self.style.sideways else (self._w, self._h)

    def path(self) -> QPainterPath:
        key = (self.style, self.text_size()[0])
        if key != self._path_key:
            self._path, _ = text_path(self.style, key[1])
            self._path_key = key
        return self._path

    def content_height(self) -> float:
        """How tall, in its own direction, the text needs the box to be."""
        return text_path(self.style, self.text_size()[0])[1]

    def fitted_rect(self, grow_only: bool) -> QRectF:
        """The rect resized across the lines (down, or right when sideways) to fit the text."""
        r = self.rect()
        need = self.content_height()
        if self.style.sideways:
            r.setWidth(max(r.width(), need) if grow_only else need)
        else:
            r.setHeight(max(r.height(), need) if grow_only else need)
        return r

    def native_ratio(self) -> float:
        return self._w / self._h

    def effective_dpi(self) -> float | None:
        return None  # vector

    def paint_content(self, painter: QPainter) -> None:
        painter.save()
        # Qt's rotate() turns clockwise on screen, so counterclockwise is negative.
        # The text's top-left corner ends up at this corner of the box.
        corner = {90: (0, self._h), 180: (self._w, self._h), 270: (self._w, 0)}
        painter.translate(*corner.get(self.style.rotation, (0, 0)))
        painter.rotate(-self.style.rotation)
        tw, th = self.text_size()
        paint_text(painter, self.style, tw, th, self.path())
        painter.restore()

    def paint(self, painter: QPainter, option: QStyleOptionGraphicsItem,
              widget: QWidget | None = None) -> None:
        self.paint_content(painter)


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

