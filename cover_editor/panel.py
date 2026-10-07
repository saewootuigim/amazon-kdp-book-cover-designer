"""The tool panel on the right: pictures, layer order, cover and selection info."""

from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QDoubleValidator, QFont, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QCheckBox, QFormLayout, QGridLayout, QGroupBox, QHBoxLayout,
                               QLabel, QLineEdit, QListWidget, QListWidgetItem, QPushButton,
                               QVBoxLayout, QWidget)

from .canvas import GUIDE_PENS, SELECT_COLOR, SNAP_COLOR, CoverView
from .layers import Layer
from .spec import PT_PER_IN, CoverSpec

KDP_MIN_DPI = 300

# The Cover box. "full" and "barcode" are shown; the rest are CoverSpec fields to type in.
COVER_ROWS = [
    ("full", "Full cover (with bleed)"),
    ("trim_width", "Page width (trim)"),
    ("trim_height", "Page height (trim)"),
    ("spine_width", "Spine width"),
    ("bleed", "Bleed"),
    ("margin", "Safe margin"),
    ("spine_margin", "Spine margin"),
    ("barcode", "Barcode area"),
]
COVER_TIPS = {
    "trim_width": "Width of the front cover, and of the back: the book's page width.",
    "trim_height": "Height of the book's pages, before the bleed is added.",
    "spine_width": "From KDP's cover calculator, or Cover setup… works it out from the page count.",
    "bleed": "Extra art on every outside edge, trimmed off after printing. KDP: 0.125 in.",
    "margin": "How far in from the trim line to keep text. KDP: 0.125 in.",
    "spine_margin": "How far in from each spine edge to keep spine text. KDP: 0.062 in.",
}

LEGEND = [
    ("trim", "Trim line", "The printed sheet is cut here."),
    ("spine", "Spine edges", "The cover folds here."),
    ("safe", "Safe area", "Keep text and faces inside."),
    ("spine-safe", "Spine safe area", "Keep spine text inside."),
    ("center", "Centre lines", "Middle of the back, spine and front, and of the height."),
    ("bleed", "Bleed", "Printed, then trimmed off. Extend background art into it."),
    ("barcode", "Barcode area", "Placeholder; Amazon prints the real barcode here."),
    ("selected", "Selected picture", "Its edges run out to the rulers."),
    ("snap", "Snap line", "Shows what a dragged picture snapped to."),
]


def legend_swatch(kind: str) -> QPixmap:
    pm = QPixmap(30, 14)
    pm.fill(QColor("#ffffff"))
    p = QPainter(pm)
    if kind == "bleed":
        p.fillRect(QRectF(0, 0, 30, 14), QColor(220, 40, 40, 60))
    elif kind == "barcode":
        p.setPen(QColor(136, 136, 136))
        p.drawRect(QRectF(5.5, 1.5, 19, 11))
        for x in (9, 11, 14, 16, 19, 21):
            p.drawLine(QPointF(x, 4), QPointF(x, 10))
    else:
        color, style = GUIDE_PENS.get(kind, (SELECT_COLOR if kind == "selected" else SNAP_COLOR,
                                             Qt.PenStyle.SolidLine))
        if kind == "selected":
            p.setPen(QPen(color, 1))
            p.setBrush(QColor("#ffffff"))
            p.drawRect(QRectF(6.5, 2.5, 17, 9))
            for x, y in ((6.5, 2.5), (23.5, 2.5), (6.5, 11.5), (23.5, 11.5)):
                p.drawRect(QRectF(x - 1.5, y - 1.5, 3, 3))
        else:
            p.setPen(QPen(color, 1.5, style))
            p.drawLine(QPointF(1, 7), QPointF(29, 7))
    p.end()
    return pm


def fmt(inches: float) -> str:
    return f"{inches:.3f}".rstrip("0").rstrip(".") if abs(inches) < 1e6 else str(inches)


class ToolPanel(QWidget):
    addRequested = Signal()
    setupRequested = Signal()
    exportRequested = Signal()
    specEdited = Signal(object)  # CoverSpec typed into the Cover box

    def __init__(self, view: CoverView, parent=None):
        super().__init__(parent)
        self.view = view
        self._syncing = False

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)

        # --- pictures -----------------------------------------------------
        pics = QGroupBox("Pictures")
        pl = QVBoxLayout(pics)
        row = QHBoxLayout()
        self.add_btn = QPushButton("Add picture…")
        self.add_btn.setToolTip("PDF, PNG, JPG, WebP, BMP, GIF, TIFF… (Ctrl+O). "
                                "You can also drag files onto the cover.")
        self.delete_btn = QPushButton("Delete")
        self.delete_btn.setToolTip("Remove the selected picture (Delete)")
        row.addWidget(self.add_btn)
        row.addWidget(self.delete_btn)
        pl.addLayout(row)
        self.layer_list = QListWidget()
        self.layer_list.setToolTip("Top of the list is the top layer. The barcode is always above all of them.")
        self.layer_list.setMinimumHeight(90)
        pl.addWidget(self.layer_list)
        root.addWidget(pics)

        # --- layer order ----------------------------------------------------
        order = QGroupBox("Layer order")
        og = QGridLayout(order)
        self.top_btn = QPushButton("⤒ Bring to front")
        self.up_btn = QPushButton("↑ Bring forward")
        self.down_btn = QPushButton("↓ Send backward")
        self.bottom_btn = QPushButton("⤓ Send to back")
        self.top_btn.setToolTip("Ctrl+Shift+]")
        self.up_btn.setToolTip("Ctrl+]")
        self.down_btn.setToolTip("Ctrl+[")
        self.bottom_btn.setToolTip("Ctrl+Shift+[")
        og.addWidget(self.top_btn, 0, 0)
        og.addWidget(self.up_btn, 0, 1)
        og.addWidget(self.bottom_btn, 1, 0)
        og.addWidget(self.down_btn, 1, 1)
        root.addWidget(order)

        # --- selected picture ----------------------------------------------
        sel = QGroupBox("Selected picture")
        sl = QVBoxLayout(sel)
        self.sel_name = QLabel("Nothing selected")
        self.sel_name.setWordWrap(True)
        bold = QFont(self.sel_name.font())
        bold.setBold(True)
        self.sel_name.setFont(bold)
        sl.addWidget(self.sel_name)

        grid = QGridLayout()
        validator = QDoubleValidator(-1000, 1000, 4)
        validator.setNotation(QDoubleValidator.Notation.StandardNotation)
        self.fields: dict[str, QLineEdit] = {}
        for i, (key, label) in enumerate((("x", "X"), ("y", "Y"), ("w", "Width"), ("h", "Height"))):
            edit = QLineEdit()
            edit.setValidator(validator)
            edit.setAlignment(Qt.AlignmentFlag.AlignRight)
            edit.setToolTip("Inches. Type a number and press Enter.")
            edit.editingFinished.connect(lambda k=key: self._field_edited(k))
            self.fields[key] = edit
            r, c = divmod(i, 2)
            grid.addWidget(QLabel(label), r, c * 3)
            grid.addWidget(edit, r, c * 3 + 1)
            grid.addWidget(QLabel("in"), r, c * 3 + 2)
        sl.addLayout(grid)

        self.keep_ratio = QCheckBox("Maintain ratio")
        self.keep_ratio.setChecked(True)
        self.keep_ratio.setToolTip("When you type a width or height, change the other one to match.")
        sl.addWidget(self.keep_ratio)

        row = QHBoxLayout()
        self.orig_ratio_btn = QPushButton("Original ratio")
        self.orig_ratio_btn.setToolTip("Undo any stretching: restore the file's own proportions, keeping the width.")
        self.fill_btn = QPushButton("Fill full cover")
        self.fill_btn.setToolTip("Scale, keeping the ratio, until it covers the whole cover including "
                                 "the bleed, centred. Anything past the edge is cut off.")
        row.addWidget(self.orig_ratio_btn)
        row.addWidget(self.fill_btn)
        sl.addLayout(row)

        self.sel_native = QLabel("")
        self.sel_dpi = QLabel("")
        self.sel_dpi.setWordWrap(True)
        sl.addWidget(self.sel_native)
        sl.addWidget(self.sel_dpi)
        root.addWidget(sel)

        # --- cover --------------------------------------------------------
        cover = QGroupBox("Cover")
        cl = QVBoxLayout(cover)
        self.cover_form = QFormLayout()
        self.cover_labels: dict[str, QLabel] = {}
        self.cover_fields: dict[str, QLineEdit] = {}
        size_validator = QDoubleValidator(0, 60, 4)
        size_validator.setNotation(QDoubleValidator.Notation.StandardNotation)
        for key, label in COVER_ROWS:
            if key in ("full", "barcode"):
                widget = QLabel()
                widget.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
                self.cover_labels[key] = widget
            else:
                edit = QLineEdit()
                edit.setValidator(size_validator)
                edit.setAlignment(Qt.AlignmentFlag.AlignRight)
                edit.setToolTip(COVER_TIPS[key])
                edit.editingFinished.connect(lambda k=key: self._cover_edited(k))
                self.cover_fields[key] = edit
                widget = QWidget()
                hl = QHBoxLayout(widget)
                hl.setContentsMargins(0, 0, 0, 0)
                hl.addWidget(edit)
                hl.addWidget(QLabel("in"))
            self.cover_form.addRow(label + ":", widget)
        cl.addLayout(self.cover_form)
        note = QLabel("Type a size and press Enter. Pictures move with the back, spine or "
                      "front they sit on.")
        note.setWordWrap(True)
        cl.addWidget(note)
        self.setup_btn = QPushButton("Cover setup…")
        self.setup_btn.setToolTip("All sizes, including the barcode area, and the spine width "
                                  "from a page count.")
        cl.addWidget(self.setup_btn)
        root.addWidget(cover)

        # --- view & export --------------------------------------------------
        viewbox = QGroupBox("View")
        vl = QVBoxLayout(viewbox)
        self.show_guides = QCheckBox("Show guides")
        self.show_guides.setChecked(True)
        self.snap = QCheckBox("Snap to guides (hold Shift to skip)")
        self.snap.setChecked(True)
        vl.addWidget(self.show_guides)
        vl.addWidget(self.snap)
        root.addWidget(viewbox)

        legendbox = QGroupBox("Legend")
        lg = QGridLayout(legendbox)
        lg.setVerticalSpacing(4)
        for i, (kind, name, what) in enumerate(LEGEND):
            swatch = QLabel()
            swatch.setPixmap(legend_swatch(kind))
            swatch.setAlignment(Qt.AlignmentFlag.AlignTop)
            text = QLabel(f"<b>{name}</b>: {what}")
            text.setWordWrap(True)
            lg.addWidget(swatch, i, 0)
            lg.addWidget(text, i, 1)
        rulers = QLabel("<b>Rulers</b>: inches from the cover's top-left corner. The rows above "
                        "the scale show the sizes of the cover's parts, its margins and safe "
                        "areas, and the selected picture. Hover a line or number, on the "
                        "rulers or the cover, for exact values.")
        rulers.setWordWrap(True)
        lg.addWidget(rulers, len(LEGEND), 0, 1, 2)
        lg.setColumnStretch(1, 1)
        root.addWidget(legendbox)

        export = QGroupBox("Export")
        el = QVBoxLayout(export)
        self.include_barcode = QCheckBox("Include barcode placeholder in PDF")
        self.include_barcode.setToolTip("Leave off for the file you upload: KDP adds the real barcode itself.")
        self.export_btn = QPushButton("Save as PDF…")
        self.export_btn.setToolTip("Ctrl+E")
        el.addWidget(self.include_barcode)
        el.addWidget(self.export_btn)
        root.addWidget(export)
        root.addStretch(1)

        # --- wiring -----------------------------------------------------------
        self.add_btn.clicked.connect(self.addRequested)
        self.setup_btn.clicked.connect(self.setupRequested)
        self.export_btn.clicked.connect(self.exportRequested)
        self.delete_btn.clicked.connect(lambda: view.selected and view.remove_layer(view.selected))
        for btn, op in ((self.top_btn, "top"), (self.up_btn, "up"),
                        (self.down_btn, "down"), (self.bottom_btn, "bottom")):
            btn.clicked.connect(lambda _=False, o=op: view.selected and view.reorder(view.selected, o))
        self.orig_ratio_btn.clicked.connect(self._original_ratio)
        self.fill_btn.clicked.connect(self._fill_cover)
        self.show_guides.toggled.connect(self._toggle_guides)
        self.snap.toggled.connect(lambda on: setattr(view, "snap_enabled", on))
        self.layer_list.currentItemChanged.connect(self._list_selected)

        view.selectionChanged.connect(self.refresh_selection)
        view.geometryChanged.connect(self._geometry_changed)
        view.layersChanged.connect(self.refresh_layers)

        self.refresh_cover(view.spec)
        self.refresh_layers()

    # --- cover ------------------------------------------------------------

    def refresh_cover(self, spec: CoverSpec) -> None:
        L = self.cover_labels
        L["full"].setText(f"<b>{fmt(spec.full_width)} × {fmt(spec.full_height)} in</b>")
        L["barcode"].setText(f"{fmt(spec.barcode_width)} × {fmt(spec.barcode_height)} in")
        for key, edit in self.cover_fields.items():
            edit.setText(fmt(getattr(spec, key)))

    def _cover_edited(self, key: str) -> None:
        spec = self.view.spec
        try:
            value = float(self.cover_fields[key].text().strip())
        except ValueError:
            value = None
        positive = key in ("trim_width", "trim_height")
        if value is None or value < 0 or (positive and value <= 0):
            self.refresh_cover(spec)  # not a usable size: put the real value back
            return
        if abs(value - getattr(spec, key)) < 1e-9:
            return
        self.specEdited.emit(replace(spec, **{key: value}))

    def _toggle_guides(self, on: bool) -> None:
        self.view.show_guides = on
        self.view.viewport().update()

    # --- layers -----------------------------------------------------------

    def refresh_layers(self) -> None:
        self._syncing = True
        self.layer_list.clear()
        for layer in reversed(self.view.layers):  # top first
            item = QListWidgetItem(layer.name)
            item.setData(Qt.ItemDataRole.UserRole, id(layer))
            self.layer_list.addItem(item)
            if layer is self.view.selected:
                self.layer_list.setCurrentItem(item)
        self._syncing = False
        self._update_buttons()

    def _list_selected(self, current: QListWidgetItem | None, _previous) -> None:
        if self._syncing:
            return
        target = None
        if current is not None:
            key = current.data(Qt.ItemDataRole.UserRole)
            target = next((l for l in self.view.layers if id(l) == key), None)
        self.view.select(target)

    def _update_buttons(self) -> None:
        layer = self.view.selected
        layers = self.view.layers
        has = layer is not None
        idx = layers.index(layer) if has else -1
        self.delete_btn.setEnabled(has)
        self.top_btn.setEnabled(has and idx < len(layers) - 1)
        self.up_btn.setEnabled(has and idx < len(layers) - 1)
        self.down_btn.setEnabled(has and idx > 0)
        self.bottom_btn.setEnabled(has and idx > 0)
        self.orig_ratio_btn.setEnabled(has)
        self.fill_btn.setEnabled(has)
        for edit in self.fields.values():
            edit.setEnabled(has)

    # --- selection --------------------------------------------------------

    def refresh_selection(self, layer: Layer | None = None) -> None:
        layer = self.view.selected
        self._syncing = True
        for i in range(self.layer_list.count()):
            item = self.layer_list.item(i)
            if layer is not None and item.data(Qt.ItemDataRole.UserRole) == id(layer):
                self.layer_list.setCurrentItem(item)
                break
        else:
            self.layer_list.setCurrentItem(None)
            self.layer_list.clearSelection()
        self._syncing = False
        self._update_buttons()
        self._show_geometry(layer)

    def _geometry_changed(self, layer: Layer) -> None:
        if layer is self.view.selected:
            self._show_geometry(layer)

    def _show_geometry(self, layer: Layer | None) -> None:
        if layer is None:
            self.sel_name.setText("Nothing selected")
            for edit in self.fields.values():
                edit.clear()
            self.sel_native.setText("")
            self.sel_dpi.setText("")
            return
        r = layer.rect()
        self.sel_name.setText(layer.name)
        values = {"x": r.x(), "y": r.y(), "w": r.width(), "h": r.height()}
        for key, edit in self.fields.items():
            edit.setText(f"{values[key] / PT_PER_IN:.3f}")
        src = layer.source
        if src.kind == "pdf":
            self.sel_native.setText(
                f"PDF page: {fmt(src.native_w / PT_PER_IN)} × {fmt(src.native_h / PT_PER_IN)} in")
            self.sel_dpi.setText("Resolution: vector (exported as-is)")
            self.sel_dpi.setStyleSheet("")
        else:
            self.sel_native.setText(f"Image: {int(src.native_w)} × {int(src.native_h)} px")
            dpi = layer.effective_dpi()
            if dpi < KDP_MIN_DPI:
                self.sel_dpi.setText(f"Resolution: {dpi:.0f} dpi — below KDP's {KDP_MIN_DPI}; "
                                     "it may print blurry at this size.")
                self.sel_dpi.setStyleSheet("color: #c0392b;")
            else:
                self.sel_dpi.setText(f"Resolution: {dpi:.0f} dpi")
                self.sel_dpi.setStyleSheet("color: #1e8449;")

    def _field_edited(self, key: str) -> None:
        layer = self.view.selected
        edit = self.fields[key]
        if layer is None:
            return
        text = edit.text().strip()
        try:
            value = float(text) * PT_PER_IN
        except ValueError:
            self._show_geometry(layer)  # not a number: put the real value back
            return
        r = layer.rect()
        ratio = r.width() / r.height()
        if key == "x":
            r.moveLeft(value)
        elif key == "y":
            r.moveTop(value)
        elif key == "w":
            if value <= 0:
                self._show_geometry(layer)
                return
            r.setWidth(value)
            if self.keep_ratio.isChecked():
                r.setHeight(value / ratio)
        else:
            if value <= 0:
                self._show_geometry(layer)
                return
            r.setHeight(value)
            if self.keep_ratio.isChecked():
                r.setWidth(value * ratio)
        if r != layer.rect():
            self.view.set_layer_rect(layer, r)
        else:
            self._show_geometry(layer)  # normalise the formatting

    def _original_ratio(self) -> None:
        layer = self.view.selected
        if layer is None:
            return
        r = layer.rect()
        center = r.center()
        r.setHeight(r.width() / layer.native_ratio())
        r.moveCenter(center)
        self.view.set_layer_rect(layer, r)

    def _fill_cover(self) -> None:
        layer = self.view.selected
        if layer is None:
            return
        page = self.view.page_rect()
        r = layer.rect()
        k = max(page.width() / r.width(), page.height() / r.height())
        r.setSize(r.size() * k)
        r.moveCenter(page.center())
        self.view.set_layer_rect(layer, r)
