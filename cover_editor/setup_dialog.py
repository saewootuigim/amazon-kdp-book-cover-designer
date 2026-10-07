"""Cover setup: trim size, spine width, bleed, margins and the barcode area."""

from __future__ import annotations

from dataclasses import fields

from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
                               QFormLayout, QGroupBox, QHBoxLayout, QLabel, QPushButton,
                               QSpinBox, QVBoxLayout)

from .spec import PAPER_THICKNESS, CoverSpec

LABELS = {
    "trim_width": "Trim width (front or back)",
    "trim_height": "Trim height",
    "spine_width": "Spine width",
    "bleed": "Bleed",
    "margin": "Safe margin",
    "spine_margin": "Spine margin (each side)",
    "barcode_width": "Barcode width",
    "barcode_height": "Barcode height",
    "barcode_margin": "Barcode margin (from back safe area's right and bottom)",
}


class CoverSetupDialog(QDialog):
    def __init__(self, spec: CoverSpec, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Cover setup")
        root = QVBoxLayout(self)

        form = QFormLayout()
        self.boxes: dict[str, QDoubleSpinBox] = {}
        for f in fields(CoverSpec):
            box = QDoubleSpinBox()
            box.setDecimals(4)
            box.setRange(0.0, 60.0)
            box.setSingleStep(0.001 if "margin" in f.name or f.name in ("bleed", "spine_width") else 0.125)
            box.setSuffix(" in")
            box.setValue(getattr(spec, f.name))
            box.valueChanged.connect(self._update_total)
            self.boxes[f.name] = box
            form.addRow(LABELS[f.name] + ":", box)
        root.addLayout(form)

        calc = QGroupBox("Spine width from page count (KDP paperback formula)")
        cl = QHBoxLayout(calc)
        self.pages = QSpinBox()
        self.pages.setRange(24, 1000)
        self.pages.setValue(max(24, round(spec.spine_width / PAPER_THICKNESS["White paper, black ink"])))
        self.paper = QComboBox()
        self.paper.addItems(list(PAPER_THICKNESS))
        apply = QPushButton("Set spine")
        apply.clicked.connect(self._apply_pages)
        cl.addWidget(QLabel("Pages:"))
        cl.addWidget(self.pages)
        cl.addWidget(self.paper, 1)
        cl.addWidget(apply)
        root.addWidget(calc)

        self.total = QLabel()
        root.addWidget(self.total)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                   | QDialogButtonBox.StandardButton.Cancel
                                   | QDialogButtonBox.StandardButton.RestoreDefaults)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.StandardButton.RestoreDefaults).clicked.connect(self._defaults)
        root.addWidget(buttons)
        self._update_total()

    def _apply_pages(self) -> None:
        self.boxes["spine_width"].setValue(self.pages.value() * PAPER_THICKNESS[self.paper.currentText()])

    def _defaults(self) -> None:
        d = CoverSpec()
        for name, box in self.boxes.items():
            box.setValue(getattr(d, name))

    def _update_total(self) -> None:
        s = self.spec()
        self.total.setText(f"Full cover with bleed: <b>{s.full_width:.3f} × {s.full_height:.3f} in</b>")

    def spec(self) -> CoverSpec:
        return CoverSpec(**{name: box.value() for name, box in self.boxes.items()})
