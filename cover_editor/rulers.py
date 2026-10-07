"""Rulers along the top and left of the canvas.

Next to the canvas each ruler has an inch scale, measured from the full cover's
top-left corner like the X and Y fields. Beyond it are three rows of dimension
lines:

- **Cover**: the bleed, back cover, spine and front cover.
- **Safe**: the margins and safe areas.
- **Picture**: the selected picture only.

The guides and the selected picture's edges run on through the ruler, so every
line on the cover can be read off it. Hovering any of them shows exact values.

Everything is drawn along one axis `u`, with the rows stacked across it in `w`.
The left ruler is the same drawing turned a quarter turn, with its text
reading upwards.
"""

from __future__ import annotations

import math
from typing import NamedTuple

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QMouseEvent, QPainter, QPen
from PySide6.QtWidgets import QGridLayout, QToolTip, QWidget

from .canvas import GUIDE_NAMES, GUIDE_PENS, SELECT_COLOR, CoverView
from .spec import PT_PER_IN, CoverSpec

ROW_PX = 15
SCALE_PX = 20
ROWS = (("Cover", QColor(60, 60, 60)), ("Safe", QColor(30, 110, 220)), ("Picture", SELECT_COLOR))
SCALE_TOP = ROW_PX * len(ROWS)
THICKNESS = SCALE_TOP + SCALE_PX

BG = QColor("#f3f3f3")
OFF_PAGE = QColor("#e1e1e1")


def fmt(inches: float) -> str:
    return f"{inches:.3f}".rstrip("0").rstrip(".") or "0"


def ruler_font() -> QFont:
    font = QFont("Segoe UI")
    font.setPixelSize(10)
    return font


class Span(NamedTuple):
    a: float  # inches from the left (top ruler) or top (left ruler) edge
    b: float
    name: str


def dimension_rows(spec: CoverSpec, picture: tuple[float, float] | None,
                   horizontal: bool) -> list[list[Span]]:
    """The Cover, Safe and Picture rows for one ruler."""
    if horizontal:
        back, spine, front = spec.back(), spec.spine(), spec.front()
        bs, ss, fs = spec.back_safe(), spec.spine_safe(), spec.front_safe()
        cover = [Span(0, back.x, "Bleed (trimmed off)"), Span(back.x, back.right, "Back cover"),
                 Span(spine.x, spine.right, "Spine"), Span(front.x, front.right, "Front cover"),
                 Span(front.right, spec.full_width, "Bleed (trimmed off)")]
        safe = [Span(back.x, bs.x, "Margin"), Span(bs.x, bs.right, "Back cover safe area"),
                Span(spine.x, ss.x, "Spine margin"), Span(ss.x, ss.right, "Spine safe area"),
                Span(ss.right, spine.right, "Spine margin"),
                Span(fs.x, fs.right, "Front cover safe area"), Span(fs.right, front.right, "Margin")]
        name = "Selected picture width"
    else:
        trim, bs = spec.trim(), spec.back_safe()
        cover = [Span(0, trim.y, "Bleed (trimmed off)"), Span(trim.y, trim.bottom, "Trim height"),
                 Span(trim.bottom, spec.full_height, "Bleed (trimmed off)")]
        safe = [Span(trim.y, bs.y, "Margin"), Span(bs.y, bs.bottom, "Safe area height"),
                Span(bs.bottom, trim.bottom, "Margin")]
        name = "Selected picture height"
    pic = [Span(picture[0], picture[1], name)] if picture else []
    return [[s for s in row if s.b - s.a > 1e-9] for row in (cover, safe, pic)]


class Ruler(QWidget):
    def __init__(self, view: CoverView, horizontal: bool, parent=None):
        super().__init__(parent)
        self.view = view
        self.horizontal = horizontal
        self._hits: list[tuple[QRectF, str]] = []  # in (u, w), for tooltips
        self._cursor: float | None = None  # inches along this ruler's axis
        self.setMouseTracking(True)
        if horizontal:
            self.setFixedHeight(THICKNESS)
        else:
            self.setFixedWidth(THICKNESS)
        view.viewChanged.connect(self.update)
        view.cursorMoved.connect(self._cursor_moved)

    def _cursor_moved(self, x: float, y: float) -> None:
        self._cursor = x if self.horizontal else y
        self.update()

    # --- mapping ------------------------------------------------------------

    def _length(self) -> int:
        return self.width() if self.horizontal else self.height()

    def _u(self, inches: float) -> float:
        """Where a cover position (inches) falls along the ruler."""
        p = self.view.viewportTransform().map(QPointF(inches * PT_PER_IN, inches * PT_PER_IN))
        origin = self.mapFromGlobal(self.view.viewport().mapToGlobal(QPoint(0, 0)))
        if self.horizontal:
            return p.x() + origin.x()
        return self.height() - (p.y() + origin.y())

    def _uw(self, pos: QPointF) -> QPointF:
        return pos if self.horizontal else QPointF(self.height() - pos.y(), pos.x())

    # --- drawing ------------------------------------------------------------

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.fillRect(self.rect(), BG)
        if not self.horizontal:
            p.translate(0, self.height())
            p.rotate(-90)
        p.setFont(ruler_font())
        self._hits = []
        spec, view = self.view.spec, self.view
        full = spec.full_width if self.horizontal else spec.full_height
        side = "left" if self.horizontal else "top"
        length = self._length()

        # The scale: grey off the page, white on it, blue under the selected picture.
        p.fillRect(QRectF(0, SCALE_TOP, length, SCALE_PX), OFF_PAGE)
        u0, u1 = sorted((self._u(0), self._u(full)))
        p.fillRect(QRectF(u0, SCALE_TOP, u1 - u0, SCALE_PX), QColor("#ffffff"))
        picture = None
        if view.selected:
            r = view.selected.rect()
            a, b = (r.left(), r.right()) if self.horizontal else (r.top(), r.bottom())
            picture = (a / PT_PER_IN, b / PT_PER_IN)
            pa, pb = sorted((self._u(picture[0]), self._u(picture[1])))
            band = QColor(SELECT_COLOR)
            band.setAlpha(45)
            p.fillRect(QRectF(pa, SCALE_TOP, pb - pa, SCALE_PX), band)
        self._draw_scale(p, length)

        # Guides and picture edges run through the whole ruler.
        if view.show_guides:
            for g in spec.guides():
                if g.vertical != self.horizontal or not g.visible or g.kind not in GUIDE_PENS:
                    continue
                color = QColor(GUIDE_PENS[g.kind][0])
                color.setAlpha(170)
                u = self._u(g.pos)
                p.setPen(QPen(color, 1))
                p.drawLine(QPointF(u, 0), QPointF(u, THICKNESS))
                self._hits.append((QRectF(u - 3, SCALE_TOP, 6, SCALE_PX),
                                   f"{GUIDE_NAMES[g.kind]}\n{g.pos:.3f} in from the {side} edge"))
        if picture:
            p.setPen(QPen(SELECT_COLOR, 1, Qt.PenStyle.DashLine))
            for v in picture:
                p.drawLine(QPointF(self._u(v), 0), QPointF(self._u(v), THICKNESS))

        for i, (row, (_, color)) in enumerate(zip(dimension_rows(spec, picture, self.horizontal), ROWS)):
            if i < 2 and not view.show_guides:
                continue
            self._draw_row(p, row, i * ROW_PX, color, side)

        if self._cursor is not None:
            u = self._u(self._cursor)
            p.setPen(QPen(QColor(0, 0, 0, 160), 1))
            p.drawLine(QPointF(u, SCALE_TOP), QPointF(u, THICKNESS))

        p.setPen(QColor("#b0b0b0"))
        p.drawLine(QPointF(0, THICKNESS - 0.5), QPointF(length, THICKNESS - 0.5))

    def _draw_scale(self, p: QPainter, length: int) -> None:
        k = self._u(1) - self._u(0)  # pixels per inch; negative on the left ruler
        ppi = abs(k)
        if ppi < 1e-6:
            return
        div = 1  # finest subdivision that keeps ticks 5 px apart
        for d in (2, 4, 8, 16):
            if ppi / d >= 5:
                div = d
        every = next((n for n in (1, 2, 5, 10, 20, 50) if ppi * n >= 28), 100)
        # Zoomed in, the halves, quarters… get numbers too, if they fit.
        label_div = max((d for d in (1, 2, 4, 8, 16) if d <= div and ppi / d >= 45), default=1)
        lo, hi = sorted(((0 - self._u(0)) / k, (length - self._u(0)) / k))
        p.setPen(QPen(QColor(90, 90, 90), 1))
        for i in range(math.floor(lo * div), math.ceil(hi * div) + 1):
            u = self._u(i / div)
            tick = 9 if i % div == 0 else {2: 6, 4: 4, 8: 3, 16: 2}[div // math.gcd(i % div, div)]
            if i % div == 0 and (i // div) % every == 0:
                label = str(i // div)
            elif i % div and (i * label_div) % div == 0:
                label = f"{i / div:g}"
            else:
                label = None
            if label:
                p.drawText(QRectF(u + 2, SCALE_TOP, 50, 12),
                           Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop, label)
            p.drawLine(QPointF(u, THICKNESS), QPointF(u, THICKNESS - tick))

    def _draw_row(self, p: QPainter, spans: list[Span], top: float, color: QColor, side: str) -> None:
        mid = top + ROW_PX / 2
        fm = p.fontMetrics()
        p.setPen(QPen(color, 1))
        overflow = []
        for s in spans:
            ua, ub = sorted((self._u(s.a), self._u(s.b)))
            p.drawLine(QPointF(ua, mid), QPointF(ub, mid))
            for u in (ua, ub):
                p.drawLine(QPointF(u, top + 3), QPointF(u, top + ROW_PX - 3))
            text = fmt(s.b - s.a)
            tip = f"{s.name}: {fmt(s.b - s.a)} in\n{s.a:.3f} to {s.b:.3f} in from the {side} edge"
            self._hits.append((QRectF(ua - 2, top, ub - ua + 4, ROW_PX), tip))
            tw = fm.horizontalAdvance(text) + 6
            if tw <= ub - ua - 4:
                r = QRectF((ua + ub) / 2 - tw / 2, top, tw, ROW_PX)
                p.fillRect(r, BG)
                p.drawText(r, Qt.AlignmentFlag.AlignCenter, text)
                self._hits.append((r, tip))
            else:
                overflow.append((ua, ub, text, tw, tip))

        # Labels too wide for their span (the spine, at most zooms) sit side by
        # side in boxes, centred on their run of neighbouring spans, in order.
        groups: list[list[tuple]] = []
        for item in sorted(overflow):
            if groups and item[0] - groups[-1][-1][1] < 1:
                groups[-1].append(item)
            else:
                groups.append([item])
        p.setBrush(BG)
        for group in groups:
            total = sum(item[3] for item in group) + 2 * (len(group) - 1)
            u = (group[0][0] + group[-1][1]) / 2 - total / 2
            for _, _, text, tw, tip in group:
                r = QRectF(u, top + 1.5, tw, ROW_PX - 3)
                p.drawRect(r)
                p.drawText(r, Qt.AlignmentFlag.AlignCenter, text)
                self._hits.append((r, tip))
                u += tw + 2
        p.setBrush(Qt.BrushStyle.NoBrush)

    # --- tooltips -----------------------------------------------------------

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        pos = self._uw(event.position())
        for r, tip in reversed(self._hits):  # labels were drawn last, so win
            if r.contains(pos):
                QToolTip.showText(event.globalPosition().toPoint(), tip, self)
                return
        QToolTip.hideText()


class RulerCorner(QWidget):
    """The square where the rulers meet; names the rows."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(THICKNESS, THICKNESS)
        self.setToolTip("Ruler rows, from the outside in (top ruler: top to bottom; left ruler: "
                        "left to right):\nCover: bleed, back cover, spine, front cover\n"
                        "Safe: margins and safe areas\nPicture: the selected picture\n"
                        "then the scale in inches from the cover's top-left corner.\n"
                        "Hover any number or line for exact values.")

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.fillRect(self.rect(), BG)
        p.setFont(ruler_font())
        for i, (name, color) in enumerate(ROWS):
            p.setPen(color)
            p.drawText(QRectF(2, i * ROW_PX, THICKNESS - 6, ROW_PX),
                       Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, name)
        p.setPen(QColor(90, 90, 90))
        p.drawText(QRectF(2, SCALE_TOP, THICKNESS - 6, SCALE_PX),
                   Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, "inches")
        p.setPen(QColor("#b0b0b0"))
        p.drawLine(QPointF(0, THICKNESS - 0.5), QPointF(THICKNESS, THICKNESS - 0.5))
        p.drawLine(QPointF(THICKNESS - 0.5, 0), QPointF(THICKNESS - 0.5, THICKNESS))


class Workspace(QWidget):
    """The canvas with its rulers."""

    def __init__(self, view: CoverView, parent=None):
        super().__init__(parent)
        self.view = view
        self.top_ruler = Ruler(view, True)
        self.left_ruler = Ruler(view, False)
        grid = QGridLayout(self)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(0)
        grid.addWidget(RulerCorner(), 0, 0)
        grid.addWidget(self.top_ruler, 0, 1)
        grid.addWidget(self.left_ruler, 1, 0)
        grid.addWidget(view, 1, 1)
