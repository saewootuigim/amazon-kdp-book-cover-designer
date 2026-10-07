"""The editing canvas.

All mouse handling lives here rather than in the items: the view decides what a
press means (grab a handle, move a picture, or nothing), applies snapping, and
draws guides, handles and snap lines as an overlay in `drawForeground`. Items
only paint themselves.

Scene units are points, so (0, 0)-(full_width*72, full_height*72) is exactly
the PDF page that export writes.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (QColor, QFont, QKeyEvent, QMouseEvent, QPainter,
                           QPainterPath, QPen, QWheelEvent)
from PySide6.QtWidgets import QFrame, QGraphicsScene, QGraphicsView, QToolTip

from .layers import BARCODE_MESSAGE, BarcodeItem, Layer, is_supported
from .spec import PT_PER_IN, CoverSpec

SNAP_PX = 8  # snap distance, in screen pixels at any zoom
HANDLE_PX = 5  # half the side of a resize handle, in screen pixels
MIN_SIZE_PT = 0.05 * PT_PER_IN

# (hx, hy): -1 = left/top, 0 = middle, 1 = right/bottom.
HANDLES = [(-1, -1), (0, -1), (1, -1), (1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0)]
HANDLE_CURSORS = {
    (-1, -1): Qt.CursorShape.SizeFDiagCursor, (1, 1): Qt.CursorShape.SizeFDiagCursor,
    (1, -1): Qt.CursorShape.SizeBDiagCursor, (-1, 1): Qt.CursorShape.SizeBDiagCursor,
    (0, -1): Qt.CursorShape.SizeVerCursor, (0, 1): Qt.CursorShape.SizeVerCursor,
    (-1, 0): Qt.CursorShape.SizeHorCursor, (1, 0): Qt.CursorShape.SizeHorCursor,
}

GUIDE_PENS = {
    "trim": (QColor(200, 30, 30), Qt.PenStyle.DashLine),
    "spine": (QColor(90, 90, 160), Qt.PenStyle.SolidLine),
    "safe": (QColor(30, 110, 220), Qt.PenStyle.DashLine),
    "spine-safe": (QColor(30, 110, 220), Qt.PenStyle.DotLine),
    "center": (QColor(40, 160, 90), Qt.PenStyle.DotLine),
}
GUIDE_NAMES = {
    "trim": "Trim line: the book is cut here",
    "spine": "Spine edge: the cover folds here",
    "safe": "Safe area border: keep text and faces inside",
    "spine-safe": "Spine safe area border: keep spine text inside",
    "center": "Centre line",
}
GUIDE_HOVER_PX = 4
SNAP_COLOR = QColor(230, 0, 200)
SELECT_COLOR = QColor(0, 120, 215)


def handle_point(r: QRectF, h: tuple[int, int]) -> QPointF:
    x = {-1: r.left(), 0: r.center().x(), 1: r.right()}[h[0]]
    y = {-1: r.top(), 0: r.center().y(), 1: r.bottom()}[h[1]]
    return QPointF(x, y)


def nearest(values: list[float], targets: list[float], threshold: float):
    """Best (delta, target) moving any of `values` onto any of `targets`, or None."""
    best = None
    for v in values:
        for t in targets:
            d = t - v
            if abs(d) <= threshold and (best is None or abs(d) < abs(best[0])):
                best = (d, t)
    return best


@dataclass
class _Drag:
    mode: str  # "move" | "resize"
    layer: Layer
    start: QRectF  # the layer's rect at press
    press: QPointF  # scene position of the press
    handle: tuple[int, int] | None = None
    grab: QPointF = field(default_factory=QPointF)  # handle position minus press position


class CoverView(QGraphicsView):
    selectionChanged = Signal(object)  # Layer or None
    geometryChanged = Signal(object)  # Layer
    layersChanged = Signal()  # added, removed or reordered
    statusMessage = Signal(str)
    cursorMoved = Signal(float, float)  # inches
    zoomChanged = Signal(float)  # percent of physical size
    filesDropped = Signal(list, QPointF)  # paths, scene position
    viewChanged = Signal()  # repainted: zoom, scroll, guides or selection may have moved

    def __init__(self, spec: CoverSpec, parent=None):
        super().__init__(parent)
        self.setScene(QGraphicsScene(self))
        self.layers: list[Layer] = []  # bottom to top
        self.selected: Layer | None = None
        self.show_guides = True
        self.snap_enabled = True

        self._drag: _Drag | None = None
        self._pan_from: QPointF | None = None
        self._last_scene = QPointF()
        self._snap_lines: list[tuple[bool, float]] = []  # (vertical, pos_pt)
        self._auto_fit = True
        self._guide_tip = False  # a guide tooltip is showing

        self.barcode = BarcodeItem()
        self.scene().addItem(self.barcode)

        self.setRenderHints(QPainter.RenderHint.Antialiasing
                            | QPainter.RenderHint.SmoothPixmapTransform)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        # The overlay is drawn in drawForeground; partial updates would leave
        # stale handles and snap lines behind.
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.FullViewportUpdate)
        self.setMouseTracking(True)
        self.setAcceptDrops(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setFrameShape(QFrame.Shape.NoFrame)  # flush against the rulers

        self.spec = spec
        self.apply_spec(spec)

    # --- cover ------------------------------------------------------------

    def apply_spec(self, spec: CoverSpec) -> None:
        self.spec = spec
        w, h = spec.full_width * PT_PER_IN, spec.full_height * PT_PER_IN
        pad = PT_PER_IN * 1.5
        self.scene().setSceneRect(QRectF(-pad, -pad, w + 2 * pad, h + 2 * pad))
        b = spec.barcode().pt()
        self.barcode.set_rect(QRectF(b.x, b.y, b.w, b.h))
        self.viewport().update()

    def change_spec(self, spec: CoverSpec) -> None:
        """Switch to a new cover size, carrying the pictures along.

        Each picture keeps its place on the part of the cover its centre is on:
        the back, spine or front across, the top or bottom half down. One that
        covered the whole cover is scaled, keeping its ratio, to cover it still,
        and one that filled the spine's width is stretched to the new spine.
        """
        old = self.spec
        ow, oh = old.full_width * PT_PER_IN, old.full_height * PT_PER_IN
        nw, nh = spec.full_width * PT_PER_IN, spec.full_height * PT_PER_IN
        os_, ns = old.spine().pt(), spec.spine().pt()
        eps = 0.5
        moved = []
        for layer in self.layers:
            r = layer.rect()
            dy = (spec.trim().y - old.trim().y if r.center().y() < oh / 2
                  else spec.trim().bottom - old.trim().bottom) * PT_PER_IN
            if r.left() <= eps and r.top() <= eps and r.right() >= ow - eps and r.bottom() >= oh - eps:
                k = max(nw / ow, nh / oh)
                c = r.center()
                r = QRectF(0, 0, r.width() * k, r.height() * k)
                r.moveCenter(QPointF(nw / 2 + (c.x() - ow / 2) * k, nh / 2 + (c.y() - oh / 2) * k))
            elif abs(r.left() - os_.x) <= eps and abs(r.right() - os_.right) <= eps:
                r = QRectF(ns.x, r.top() + dy, ns.w, r.height())
            else:
                cx = r.center().x() / PT_PER_IN
                if cx < old.spine().x:
                    dx = spec.back().x - old.back().x
                elif cx > old.spine().right:
                    dx = spec.front().x - old.front().x
                else:
                    dx = spec.spine().cx - old.spine().cx
                r = r.translated(dx * PT_PER_IN, dy)
            moved.append((layer, r))
        self.apply_spec(spec)
        for layer, r in moved:
            self.set_layer_rect(layer, r)

    def page_rect(self) -> QRectF:
        return QRectF(0, 0, self.spec.full_width * PT_PER_IN, self.spec.full_height * PT_PER_IN)

    # --- layers -----------------------------------------------------------

    def add_layer(self, layer: Layer, center: QPointF | None = None) -> None:
        """Add on top. A picture bigger than the cover is shrunk to fit it."""
        page = self.page_rect()
        r = layer.rect()
        k = min(1.0, page.width() / r.width(), page.height() / r.height())
        r.setSize(r.size() * k)
        r.moveCenter(center if center is not None else page.center())
        layer.set_rect(r)
        self.scene().addItem(layer)
        self.layers.append(layer)
        self._restack()
        self.select(layer)
        self.layersChanged.emit()

    def remove_layer(self, layer: Layer) -> None:
        if layer not in self.layers:
            return
        if self._drag and self._drag.layer is layer:
            self._drag = None
        self.layers.remove(layer)
        self.scene().removeItem(layer)
        if self.selected is layer:
            self.select(None)
        self._restack()
        self.layersChanged.emit()

    def clear_layers(self) -> None:
        for layer in list(self.layers):
            self.scene().removeItem(layer)
        self.layers.clear()
        self._drag = None
        self.select(None)
        self.layersChanged.emit()

    def reorder(self, layer: Layer, op: str) -> None:
        """op: 'up', 'down', 'top' or 'bottom'."""
        if layer not in self.layers:
            return
        i = self.layers.index(layer)
        j = {"up": i + 1, "down": i - 1, "top": len(self.layers) - 1, "bottom": 0}[op]
        j = max(0, min(len(self.layers) - 1, j))
        if i == j:
            return
        self.layers.insert(j, self.layers.pop(i))
        self._restack()
        self.layersChanged.emit()

    def _restack(self) -> None:
        for z, layer in enumerate(self.layers):
            layer.setZValue(z)  # the barcode sits far above, at BarcodeItem.Z

    def select(self, layer: Layer | None) -> None:
        if layer is self.selected:
            return
        self.selected = layer
        self.viewport().update()
        self.selectionChanged.emit(layer)

    def set_layer_rect(self, layer: Layer, r: QRectF) -> None:
        layer.set_rect(r)
        self.viewport().update()
        self.geometryChanged.emit(layer)

    # --- zoom -------------------------------------------------------------

    def _scale(self) -> float:
        return self.transform().m11()  # screen pixels per point

    def zoom_percent(self) -> float:
        return self._scale() * PT_PER_IN / self.logicalDpiX() * 100

    def zoom_by(self, factor: float) -> None:
        s = self._scale()
        factor = max(0.02 / s, min(60 / s, factor))
        self._auto_fit = False
        self.scale(factor, factor)
        self.zoomChanged.emit(self.zoom_percent())

    def fit(self) -> None:
        self._auto_fit = True
        m = PT_PER_IN * 0.3
        self.fitInView(self.page_rect().adjusted(-m, -m, m, m), Qt.AspectRatioMode.KeepAspectRatio)
        self.zoomChanged.emit(self.zoom_percent())

    def actual_size(self) -> None:
        self.zoom_by(100 / self.zoom_percent())

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._auto_fit:
            self.fit()

    def wheelEvent(self, event: QWheelEvent) -> None:
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.zoom_by(1.15 ** (event.angleDelta().y() / 120))
            event.accept()
        else:
            super().wheelEvent(event)

    # --- hit testing ----------------------------------------------------------

    def _layer_at(self, sp: QPointF) -> Layer | None:
        for item in self.scene().items(sp):  # topmost first
            if isinstance(item, Layer):
                return item
        return None

    def _handle_at(self, vp: QPointF) -> tuple[int, int] | None:
        if not self.selected:
            return None
        r = self.selected.rect()
        reach = HANDLE_PX + 3
        for h in HANDLES:
            p = self.mapFromScene(handle_point(r, h))
            if abs(p.x() - vp.x()) <= reach and abs(p.y() - vp.y()) <= reach:
                return h
        return None

    def _guide_at(self, vp: QPointF):
        if not self.show_guides:
            return None
        sp = self.mapToScene(vp.toPoint())
        reach = GUIDE_HOVER_PX / self._scale()
        best = None
        for g in self.spec.guides():
            if not g.visible or g.kind not in GUIDE_NAMES:
                continue
            d = abs((sp.x() if g.vertical else sp.y()) - g.pos * PT_PER_IN)
            if d <= reach and (best is None or d < best[0]):
                best = (d, g)
        return best[1] if best else None

    def _show_guide_tip(self, event: QMouseEvent) -> None:
        g = self._guide_at(event.position())
        if g:
            side = "left" if g.vertical else "top"
            QToolTip.showText(event.globalPosition().toPoint(),
                              f"{GUIDE_NAMES[g.kind]}\n{g.pos:.3f} in from the {side} edge", self.viewport())
            self._guide_tip = True
        elif self._guide_tip:
            QToolTip.hideText()
            self._guide_tip = False

    # --- snapping -------------------------------------------------------------

    def _targets(self, exclude: Layer) -> tuple[list[float], list[float]]:
        xs = [g.pos * PT_PER_IN for g in self.spec.guides() if g.vertical]
        ys = [g.pos * PT_PER_IN for g in self.spec.guides() if not g.vertical]
        for other in self.layers:  # line up with the other pictures too
            if other is exclude:
                continue
            r = other.rect()
            xs += [r.left(), r.center().x(), r.right()]
            ys += [r.top(), r.center().y(), r.bottom()]
        return xs, ys

    def _apply_drag(self, sp: QPointF, modifiers) -> None:
        d = self._drag
        snapping = self.snap_enabled and not (modifiers & Qt.KeyboardModifier.ShiftModifier)
        threshold = SNAP_PX / self._scale()
        xs, ys = self._targets(d.layer) if snapping else ([], [])
        self._snap_lines = []

        if d.mode == "move":
            r = d.start.translated(sp - d.press)
            if snapping:
                sx = nearest([r.left(), r.center().x(), r.right()], xs, threshold)
                sy = nearest([r.top(), r.center().y(), r.bottom()], ys, threshold)
                if sx:
                    r.translate(sx[0], 0)
                    self._snap_lines.append((True, sx[1]))
                if sy:
                    r.translate(0, sy[0])
                    self._snap_lines.append((False, sy[1]))
        else:
            r = self._resized(sp + d.grab, snapping, xs, ys, threshold)

        self.set_layer_rect(d.layer, r)

    def _resized(self, p: QPointF, snapping: bool, xs, ys, threshold) -> QRectF:
        d = self._drag
        hx, hy = d.handle
        r0 = d.start
        x0, y0, x1, y1 = r0.left(), r0.top(), r0.right(), r0.bottom()

        if hx and hy:
            # Corner: scale about the opposite corner, keeping the ratio.
            ax = x1 if hx < 0 else x0
            ay = y1 if hy < 0 else y0
            w0, h0 = r0.width(), r0.height()
            s = max((p.x() - ax) * hx / w0, (p.y() - ay) * hy / h0)
            if snapping:
                # Snap whichever moving edge is closer to a guide; the ratio
                # then fixes the other one.
                options = []
                sx = nearest([ax + hx * w0 * s], xs, threshold)
                if sx:
                    options.append((abs(sx[0]), (sx[1] - ax) * hx / w0, (True, sx[1])))
                sy = nearest([ay + hy * h0 * s], ys, threshold)
                if sy:
                    options.append((abs(sy[0]), (sy[1] - ay) * hy / h0, (False, sy[1])))
                if options:
                    _, s_snap, line = min(options, key=lambda o: o[0])
                    if s_snap * min(w0, h0) >= MIN_SIZE_PT:
                        s = s_snap
                        self._snap_lines.append(line)
            s = max(s, MIN_SIZE_PT / min(w0, h0))
            w, h = w0 * s, h0 * s
            return QRectF(ax if hx > 0 else ax - w, ay if hy > 0 else ay - h, w, h)

        # Edge: move that one edge, freely.
        if hx:
            edge = p.x()
            if snapping and (sx := nearest([edge], xs, threshold)):
                edge = sx[1]
                self._snap_lines.append((True, edge))
            if hx > 0:
                x1 = max(edge, x0 + MIN_SIZE_PT)
            else:
                x0 = min(edge, x1 - MIN_SIZE_PT)
        if hy:
            edge = p.y()
            if snapping and (sy := nearest([edge], ys, threshold)):
                edge = sy[1]
                self._snap_lines.append((False, edge))
            if hy > 0:
                y1 = max(edge, y0 + MIN_SIZE_PT)
            else:
                y0 = min(edge, y1 - MIN_SIZE_PT)
        return QRectF(QPointF(x0, y0), QPointF(x1, y1))

    # --- mouse ------------------------------------------------------------

    def mousePressEvent(self, event: QMouseEvent) -> None:
        vp = event.position()
        sp = self.mapToScene(vp.toPoint())
        self.setFocus()

        if event.button() == Qt.MouseButton.MiddleButton:
            self._pan_from = vp
            self.viewport().setCursor(Qt.CursorShape.ClosedHandCursor)
            return
        if event.button() != Qt.MouseButton.LeftButton:
            return

        handle = self._handle_at(vp)
        if handle:
            r = self.selected.rect()
            self._drag = _Drag("resize", self.selected, r, sp, handle,
                               handle_point(r, handle) - sp)
            return

        # The barcode is on top of everything, so a click on it lands on it.
        if self.barcode.rect().contains(sp):
            self.statusMessage.emit(BARCODE_MESSAGE)
            return

        layer = self._layer_at(sp)
        self.select(layer)
        if layer:
            self._drag = _Drag("move", layer, layer.rect(), sp)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        vp = event.position()
        sp = self.mapToScene(vp.toPoint())
        self._last_scene = sp
        self.cursorMoved.emit(sp.x() / PT_PER_IN, sp.y() / PT_PER_IN)

        if self._pan_from is not None:
            delta = vp - self._pan_from
            self._pan_from = vp
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - round(delta.x()))
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - round(delta.y()))
            return
        if self._drag:
            self._apply_drag(sp, event.modifiers())
            return

        self._show_guide_tip(event)
        handle = self._handle_at(vp)
        if handle:
            self.viewport().setCursor(HANDLE_CURSORS[handle])
        elif self.barcode.rect().contains(sp):
            self.viewport().setCursor(Qt.CursorShape.ForbiddenCursor)
        elif self._layer_at(sp):
            self.viewport().setCursor(Qt.CursorShape.SizeAllCursor)
        else:
            self.viewport().unsetCursor()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.MiddleButton and self._pan_from is not None:
            self._pan_from = None
            self.viewport().unsetCursor()
            return
        if event.button() == Qt.MouseButton.LeftButton and self._drag:
            self._drag = None
            self._snap_lines = []
            self.viewport().update()

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        self.mousePressEvent(event)

    # --- keyboard ---------------------------------------------------------

    def keyPressEvent(self, event: QKeyEvent) -> None:
        key = event.key()
        if key == Qt.Key.Key_Shift and self._drag:
            self._apply_drag(self._last_scene, event.modifiers())  # snapping off now
            return
        if self.selected and key in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            self.remove_layer(self.selected)
            return
        arrows = {Qt.Key.Key_Left: (-1, 0), Qt.Key.Key_Right: (1, 0),
                  Qt.Key.Key_Up: (0, -1), Qt.Key.Key_Down: (0, 1)}
        if self.selected and key in arrows and not self._drag:
            step = 0.1 if event.modifiers() & Qt.KeyboardModifier.ShiftModifier else 0.01
            dx, dy = arrows[key]
            self.set_layer_rect(self.selected, self.selected.rect().translated(
                dx * step * PT_PER_IN, dy * step * PT_PER_IN))
            return
        if key == Qt.Key.Key_Escape and self.selected and not self._drag:
            self.select(None)
            return
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Shift and self._drag:
            self._apply_drag(self._last_scene, event.modifiers())  # snapping back on
            return
        super().keyReleaseEvent(event)

    # --- drag and drop from Explorer --------------------------------------------

    def _dropped_paths(self, event) -> list[str]:
        if not event.mimeData().hasUrls():
            return []
        return [u.toLocalFile() for u in event.mimeData().urls()
                if u.isLocalFile() and is_supported(u.toLocalFile())]

    def dragEnterEvent(self, event) -> None:
        if self._dropped_paths(event):
            event.acceptProposedAction()

    def dragMoveEvent(self, event) -> None:
        if self._dropped_paths(event):
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        paths = self._dropped_paths(event)
        if paths:
            event.acceptProposedAction()
            self.filesDropped.emit(paths, self.mapToScene(event.position().toPoint()))

    # --- drawing ----------------------------------------------------------

    def drawBackground(self, painter: QPainter, rect: QRectF) -> None:
        painter.fillRect(rect, QColor("#5b5e63"))
        page = self.page_rect()
        painter.fillRect(page.translated(3 / self._scale(), 3 / self._scale()), QColor(0, 0, 0, 70))
        painter.fillRect(page, QColor("#ffffff"))

    def drawForeground(self, painter: QPainter, rect: QRectF) -> None:
        page = self.page_rect()
        spec = self.spec
        visible = self.mapToScene(self.viewport().rect()).boundingRect()

        # Dim whatever hangs past the page edge: it will be cut off in the PDF.
        outside = QPainterPath()
        outside.addRect(self.sceneRect().united(rect))
        inner = QPainterPath()
        inner.addRect(page)
        painter.fillPath(outside.subtracted(inner), QColor(70, 72, 76, 185))

        if self.show_guides:
            # Bleed: printed, then trimmed away.
            t = spec.trim().pt()
            band = QPainterPath()
            band.addRect(page)
            trim = QPainterPath()
            trim.addRect(QRectF(t.x, t.y, t.w, t.h))
            painter.fillPath(band.subtracted(trim), QColor(220, 40, 40, 38))

            for g in spec.guides():
                if not g.visible or g.kind not in GUIDE_PENS:
                    continue
                color, style = GUIDE_PENS[g.kind]
                faded = QColor(color)
                faded.setAlpha(110)
                v = g.pos * PT_PER_IN
                end = page.height() if g.vertical else page.width()
                far0, far1 = (visible.top(), visible.bottom()) if g.vertical else (visible.left(), visible.right())
                # Full strength on the page, fainter beyond it, out to the rulers.
                for c, a, b in ((color, 0, end), (faded, far0, 0), (faded, end, far1)):
                    pen = QPen(c, 1, style)
                    pen.setCosmetic(True)
                    painter.setPen(pen)
                    if g.vertical:
                        painter.drawLine(QPointF(v, a), QPointF(v, b))
                    else:
                        painter.drawLine(QPointF(a, v), QPointF(b, v))

            font = QFont("Segoe UI")
            font.setPixelSize(11)
            font.setBold(True)
            painter.setFont(font)
            painter.setPen(QColor(90, 90, 160, 130))
            for label, r in (("BACK COVER", spec.back_safe()), ("FRONT COVER", spec.front_safe())):
                rp = r.pt()
                painter.drawText(QRectF(rp.x, rp.y + 4, rp.w, 20),
                                 Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, label)

        border = QPen(QColor("#202020"), 1)
        border.setCosmetic(True)
        painter.setPen(border)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(page)

        for vertical, v in self._snap_lines:
            pen = QPen(SNAP_COLOR, 1)
            pen.setCosmetic(True)
            painter.setPen(pen)
            sr = self.sceneRect()
            if vertical:
                painter.drawLine(QPointF(v, sr.top()), QPointF(v, sr.bottom()))
            else:
                painter.drawLine(QPointF(sr.left(), v), QPointF(sr.right(), v))

        if self.selected:
            r = self.selected.rect()
            # Its edges run out to the rulers, where its size is shown.
            edge = QColor(SELECT_COLOR)
            edge.setAlpha(150)
            pen = QPen(edge, 1, Qt.PenStyle.DashLine)
            pen.setCosmetic(True)
            painter.setPen(pen)
            for x in (r.left(), r.right()):
                painter.drawLine(QPointF(x, visible.top()), QPointF(x, r.top()))
            for y in (r.top(), r.bottom()):
                painter.drawLine(QPointF(visible.left(), y), QPointF(r.left(), y))
            painter.save()
            painter.resetTransform()  # handles are a fixed size on screen
            pen = QPen(SELECT_COLOR, 1)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            tl, br = self.mapFromScene(r.topLeft()), self.mapFromScene(r.bottomRight())
            painter.drawRect(QRectF(QPointF(tl), QPointF(br)))
            painter.setBrush(QColor("#ffffff"))
            for h in HANDLES:
                c = self.mapFromScene(handle_point(r, h))
                painter.drawRect(QRectF(c.x() - HANDLE_PX, c.y() - HANDLE_PX,
                                        2 * HANDLE_PX, 2 * HANDLE_PX))
            painter.restore()

        self.viewChanged.emit()
