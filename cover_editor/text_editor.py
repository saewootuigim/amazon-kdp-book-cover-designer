"""The text editor: a small floating window for the selected text box.

It follows the selection. Every change is applied to the box at once; the box
grows taller when the text no longer fits, but never shrinks by itself.
"""

from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QColorDialog, QDialog, QDoubleSpinBox,
                               QFontComboBox, QFormLayout, QHBoxLayout, QLabel, QPlainTextEdit,
                               QPushButton, QToolButton, QVBoxLayout, QWidget)

from .canvas import CoverView
from .layers import Layer, TextLayer, TextStyle


class ColorButton(QPushButton):
    """A swatch that opens a color picker."""

    colorChanged = Signal(str)

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self._title = title
        self._color = "#000000"
        self.setFixedWidth(64)
        self.clicked.connect(self._pick)

    def color(self) -> str:
        return self._color

    def set_color(self, color: str) -> None:
        self._color = color
        pm = QPixmap(36, 14)
        pm.fill(QColor(color))
        p = QPainter(pm)
        p.setPen(QColor("#808080"))  # so white still shows on the button
        p.drawRect(0, 0, pm.width() - 1, pm.height() - 1)
        p.end()
        self.setIcon(QIcon(pm))
        self.setIconSize(pm.size())

    def _pick(self) -> None:
        c = QColorDialog.getColor(QColor(self._color), self, self._title)
        if c.isValid() and c.name() != self._color:
            self.set_color(c.name())
            self.colorChanged.emit(c.name())


class TextEditor(QDialog):
    def __init__(self, view: CoverView, parent=None):
        super().__init__(parent)
        self.view = view
        self.layer: TextLayer | None = None
        self._loading = False
        self.setWindowTitle("Text")
        self.setWindowFlag(Qt.WindowType.Tool)

        root = QVBoxLayout(self)
        self.hint = QLabel("Select a text box on the cover to edit it.")
        self.hint.setWordWrap(True)
        root.addWidget(self.hint)

        self.text = QPlainTextEdit()
        self.text.setPlaceholderText("Type your text")
        self.text.setMinimumHeight(90)
        root.addWidget(self.text)

        self.controls = QWidget()
        form = QFormLayout(self.controls)
        form.setContentsMargins(0, 0, 0, 0)

        self.font_box = QFontComboBox()
        form.addRow("Font:", self.font_box)

        row = QHBoxLayout()
        self.size = QDoubleSpinBox()
        self.size.setRange(2, 500)
        self.size.setDecimals(1)
        self.size.setSuffix(" pt")
        row.addWidget(self.size)
        self.bold = QToolButton()
        self.bold.setText("B")
        self.bold.setCheckable(True)
        self.bold.setToolTip("Bold")
        f = self.bold.font()
        f.setBold(True)
        self.bold.setFont(f)
        self.italic = QToolButton()
        self.italic.setText("I")
        self.italic.setCheckable(True)
        self.italic.setToolTip("Italic")
        f = self.italic.font()
        f.setItalic(True)
        self.italic.setFont(f)
        row.addWidget(self.bold)
        row.addWidget(self.italic)
        row.addSpacing(8)
        self.align = QButtonGroup(self)
        for key, label in (("left", "Left"), ("center", "Center"), ("right", "Right")):
            b = QToolButton()
            b.setText(label)
            b.setCheckable(True)
            b.setProperty("align", key)
            self.align.addButton(b)
            row.addWidget(b)
        row.addStretch(1)
        form.addRow("Size:", row)

        self.color = ColorButton("Text color")
        form.addRow("Color:", self.color)

        row = QHBoxLayout()
        self.background = QCheckBox("Colored")
        self.background.setToolTip("Off: transparent, the cover shows through behind the text.")
        self.background_color = ColorButton("Background color")
        row.addWidget(self.background)
        row.addWidget(self.background_color)
        row.addStretch(1)
        form.addRow("Background:", row)

        row = QHBoxLayout()
        self.outline = QCheckBox("Colored")
        self.outline.setToolTip("Off: transparent, no outline around the letters.")
        self.outline_color = ColorButton("Outline color")
        self.outline_width = QDoubleSpinBox()
        self.outline_width.setRange(0.1, 20)
        self.outline_width.setDecimals(2)
        self.outline_width.setSingleStep(0.25)
        self.outline_width.setSuffix(" pt")
        self.outline_width.setToolTip("Outline thickness, outside the letters")
        row.addWidget(self.outline)
        row.addWidget(self.outline_color)
        row.addWidget(self.outline_width)
        row.addStretch(1)
        form.addRow("Font outline:", row)
        root.addWidget(self.controls)

        buttons = QHBoxLayout()
        self.fit_btn = QPushButton("Fit box to text")
        self.fit_btn.setToolTip("Make the box exactly as tall as its text")
        self.rotate_btn = QPushButton("⟲ Rotate")
        self.rotate_btn.setToolTip("Turn the text box a quarter turn counterclockwise")
        close = QPushButton("Close")
        close.clicked.connect(self.close)
        buttons.addWidget(self.fit_btn)
        buttons.addWidget(self.rotate_btn)
        buttons.addStretch(1)
        buttons.addWidget(close)
        root.addLayout(buttons)

        self.text.textChanged.connect(self._changed)
        self.font_box.currentFontChanged.connect(self._changed)
        self.size.valueChanged.connect(self._changed)
        self.bold.toggled.connect(self._changed)
        self.italic.toggled.connect(self._changed)
        self.align.buttonToggled.connect(lambda _b, on: on and self._changed())
        for w in (self.color, self.background_color, self.outline_color):
            w.colorChanged.connect(self._changed)
        self.background.toggled.connect(self._changed)
        self.outline.toggled.connect(self._changed)
        self.outline_width.valueChanged.connect(self._changed)
        self.fit_btn.clicked.connect(self._fit)
        self.rotate_btn.clicked.connect(lambda: self.layer and self.view.rotate_text(self.layer))
        view.selectionChanged.connect(self.edit)

        self.resize(440, 340)
        self.edit(view.selected)

    def edit(self, layer: Layer | None) -> None:
        """Show `layer`'s text, or disable everything if it isn't a text box."""
        self.layer = layer if isinstance(layer, TextLayer) else None
        on = self.layer is not None
        self.hint.setVisible(not on)
        for w in (self.text, self.controls, self.fit_btn, self.rotate_btn):
            w.setEnabled(on)
        if not on:
            return
        s = self.layer.style
        self._loading = True
        if self.text.toPlainText() != s.text:
            self.text.setPlainText(s.text)
        self.font_box.setCurrentFont(QFont(s.family))
        self.size.setValue(s.size)
        self.bold.setChecked(s.bold)
        self.italic.setChecked(s.italic)
        for b in self.align.buttons():
            b.setChecked(b.property("align") == s.align)
        self.color.set_color(s.color)
        self.background.setChecked(s.background)
        self.background_color.set_color(s.background_color)
        self.outline.setChecked(s.outline)
        self.outline_color.set_color(s.outline_color)
        self.outline_width.setValue(s.outline_width)
        self._loading = False

    def style(self) -> TextStyle:
        checked = self.align.checkedButton()
        return replace(
            self.layer.style if self.layer else TextStyle(),
            text=self.text.toPlainText(), family=self.font_box.currentFont().family(),
            size=self.size.value(), bold=self.bold.isChecked(), italic=self.italic.isChecked(),
            align=checked.property("align") if checked else "left",
            color=self.color.color(), background=self.background.isChecked(),
            background_color=self.background_color.color(), outline=self.outline.isChecked(),
            outline_color=self.outline_color.color(), outline_width=self.outline_width.value())

    def _changed(self, *_) -> None:
        if self._loading or self.layer is None:
            return
        self.view.set_text_style(self.layer, self.style())

    def _fit(self) -> None:
        if self.layer is not None:
            self.view.set_layer_rect(self.layer, self.layer.fitted_rect(grow_only=False))
