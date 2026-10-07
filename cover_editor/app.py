"""Main window: menus, the canvas, the tool panel and the status bar."""

from __future__ import annotations

import os
import sys

from PySide6.QtCore import QPointF, QSettings, Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (QApplication, QDockWidget, QFileDialog, QInputDialog, QLabel,
                               QMainWindow, QMessageBox, QScrollArea)

from .canvas import CoverView
from .export import export_pdf
from .layers import IMAGE_EXTS, PDF_EXTS, Layer, is_supported, load_source, pdf_page_count
from .panel import ToolPanel
from .project import load_project, save_project
from .rulers import Workspace
from .setup_dialog import CoverSetupDialog
from .spec import CoverSpec

APP_NAME = "Book Cover Editor"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Settings live in the app folder, not the registry, so nothing leaks outside it.
SETTINGS_FILE = os.path.join(ROOT, "settings.ini")

PICTURE_FILTER = ("Pictures and PDFs (" + " ".join("*" + e for e in PDF_EXTS + IMAGE_EXTS) + ");;"
                  "PDF (*.pdf);;Images (" + " ".join("*" + e for e in IMAGE_EXTS) + ");;All files (*)")
PROJECT_FILTER = "Cover project (*.cover.json);;JSON (*.json)"


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings = QSettings(SETTINGS_FILE, QSettings.Format.IniFormat)
        self.project_path: str | None = None
        self.modified = False

        self.view = CoverView(CoverSpec())
        workspace = Workspace(self.view)
        self.top_ruler, self.left_ruler = workspace.top_ruler, workspace.left_ruler
        self.setCentralWidget(workspace)

        self.panel = ToolPanel(self.view)
        scroll = QScrollArea()
        scroll.setWidget(self.panel)
        scroll.setWidgetResizable(True)
        scroll.setMinimumWidth(330)
        dock = QDockWidget("Tools")
        dock.setObjectName("tools")
        dock.setWidget(scroll)
        dock.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetMovable
                         | QDockWidget.DockWidgetFeature.DockWidgetFloatable)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)

        self.pos_label = QLabel()
        self.zoom_label = QLabel()
        self.statusBar().addPermanentWidget(self.pos_label)
        self.statusBar().addPermanentWidget(self.zoom_label)

        self._build_menus()

        self.panel.addRequested.connect(self.add_pictures)
        self.panel.setupRequested.connect(self.cover_setup)
        self.panel.specEdited.connect(self.change_spec)
        self.panel.exportRequested.connect(self.export)
        self.view.statusMessage.connect(lambda m: self.statusBar().showMessage(m, 6000))
        self.view.cursorMoved.connect(lambda x, y: self.pos_label.setText(f"{x:.3f}, {y:.3f} in"))
        self.view.zoomChanged.connect(lambda z: self.zoom_label.setText(f"Zoom {z:.0f}%"))
        self.view.filesDropped.connect(self._files_dropped)
        self.view.layersChanged.connect(self._touch)
        self.view.geometryChanged.connect(self._touch)

        self.resize(1400, 860)
        geometry = self.settings.value("window/geometry")
        if geometry is not None:
            self.restoreGeometry(geometry)
        self._update_title()
        self.statusBar().showMessage(
            "Add a picture (Ctrl+O) or drag files onto the cover. "
            "Drag to move, corner handles keep the ratio, edge handles stretch, Shift skips snapping.")

    # --- menus ------------------------------------------------------------

    def _action(self, menu, text, slot, shortcut=None) -> QAction:
        act = QAction(text, self)
        if shortcut:
            act.setShortcut(QKeySequence(shortcut))
        act.triggered.connect(slot)
        menu.addAction(act)
        return act

    def _build_menus(self) -> None:
        m = self.menuBar().addMenu("&File")
        self._action(m, "&New cover", self.new_cover, QKeySequence.StandardKey.New)
        self._action(m, "Open &project…", self.open_project, "Ctrl+Shift+O")
        self._action(m, "&Save project", self.save_project, QKeySequence.StandardKey.Save)
        self._action(m, "Save project &as…", self.save_project_as, "Ctrl+Shift+S")
        m.addSeparator()
        self._action(m, "&Add picture…", self.add_pictures, "Ctrl+O")
        self._action(m, "Save as P&DF…", self.export, "Ctrl+E")
        m.addSeparator()
        self._action(m, "E&xit", self.close, "Alt+F4")

        m = self.menuBar().addMenu("&Arrange")
        sel = lambda op: (lambda: self.view.selected and self.view.reorder(self.view.selected, op))
        self._action(m, "Bring to &front", sel("top"), "Ctrl+Shift+]")
        self._action(m, "Bring &forward", sel("up"), "Ctrl+]")
        self._action(m, "Send &backward", sel("down"), "Ctrl+[")
        self._action(m, "Send to bac&k", sel("bottom"), "Ctrl+Shift+[")
        m.addSeparator()
        self._action(m, "&Delete picture",
                     lambda: self.view.selected and self.view.remove_layer(self.view.selected))

        m = self.menuBar().addMenu("&View")
        self._action(m, "Zoom &in", lambda: self.view.zoom_by(1.25), "Ctrl+=")
        self._action(m, "Zoom &out", lambda: self.view.zoom_by(0.8), "Ctrl+-")
        self._action(m, "&Fit cover", self.view.fit, "Ctrl+0")
        self._action(m, "&Actual size", self.view.actual_size, "Ctrl+1")

        m = self.menuBar().addMenu("&Cover")
        self._action(m, "Cover &setup…", self.cover_setup)

        m = self.menuBar().addMenu("&Help")
        self._action(m, "&How to use", self.show_help, "F1")

    # --- state ------------------------------------------------------------

    def _touch(self, *_):
        if not self.modified:
            self.modified = True
            self._update_title()

    def _update_title(self) -> None:
        name = os.path.basename(self.project_path) if self.project_path else "Untitled"
        self.setWindowTitle(f"{'*' if self.modified else ''}{name} — {APP_NAME}")

    def _confirm_discard(self) -> bool:
        if not self.modified or not self.view.layers:
            return True
        answer = QMessageBox.question(
            self, APP_NAME, "Save the layout as a project before continuing?",
            QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel)
        if answer == QMessageBox.StandardButton.Save:
            return self.save_project()
        return answer == QMessageBox.StandardButton.Discard

    def _dir(self, key: str) -> str:
        return self.settings.value(f"dirs/{key}", os.path.expanduser("~"))

    def _remember_dir(self, key: str, path: str) -> None:
        self.settings.setValue(f"dirs/{key}", os.path.dirname(os.path.abspath(path)))

    # --- pictures ---------------------------------------------------------

    def add_pictures(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "Add picture", self._dir("pictures"), PICTURE_FILTER)
        if paths:
            self._remember_dir("pictures", paths[0])
            self.add_files(paths)

    def _files_dropped(self, paths: list, at: QPointF) -> None:
        self.add_files(paths, at)

    def add_files(self, paths: list[str], at: QPointF | None = None) -> None:
        for path in paths:
            if not is_supported(path):
                QMessageBox.warning(self, APP_NAME, f"Not a supported picture or PDF:\n{path}")
                continue
            page = 0
            try:
                if path.lower().endswith(PDF_EXTS):
                    count = pdf_page_count(path)
                    if count > 1:
                        page, ok = QInputDialog.getInt(
                            self, "Choose a page", f"{os.path.basename(path)} has {count} pages.\n"
                            "Which one do you want to place?", 1, 1, count)
                        if not ok:
                            continue
                        page -= 1
                source = load_source(path, page)
            except Exception as exc:
                QMessageBox.warning(self, APP_NAME, f"Could not open {os.path.basename(path)}:\n{exc}")
                continue
            self.view.add_layer(Layer(source), at)
            self.statusBar().showMessage(f"Added {source.name}", 4000)

    # --- cover ------------------------------------------------------------

    def cover_setup(self) -> None:
        dlg = CoverSetupDialog(self.view.spec, self)
        if dlg.exec():
            self.change_spec(dlg.spec())

    def change_spec(self, spec: CoverSpec) -> None:
        if spec == self.view.spec:
            return
        self.view.change_spec(spec)
        self.panel.refresh_cover(self.view.spec)
        self._touch()
        if self.view._auto_fit:
            self.view.fit()
        s = self.view.spec
        self.statusBar().showMessage(f"Full cover is now {s.full_width:.3f} × {s.full_height:.3f} in", 6000)

    def new_cover(self) -> None:
        if not self._confirm_discard():
            return
        self.view.clear_layers()
        self.view.apply_spec(CoverSpec())
        self.panel.refresh_cover(self.view.spec)
        self.project_path = None
        self.modified = False
        self._update_title()
        self.view.fit()

    # --- projects ---------------------------------------------------------

    def open_project(self, path: str | None = None) -> None:
        if not self._confirm_discard():
            return
        if not path:
            path, _ = QFileDialog.getOpenFileName(self, "Open project", self._dir("project"), PROJECT_FILTER)
            if not path:
                return
        try:
            spec, layers, problems = load_project(path)
        except Exception as exc:
            QMessageBox.warning(self, APP_NAME, f"Could not open the project:\n{exc}")
            return
        self._remember_dir("project", path)
        self.view.clear_layers()
        self.view.apply_spec(spec)
        self.panel.refresh_cover(spec)
        for layer in layers:
            # Placed straight from the file: add_layer would re-centre them.
            self.view.scene().addItem(layer)
            self.view.layers.append(layer)
        self.view._restack()
        self.view.layersChanged.emit()
        self.view.select(None)
        self.project_path = path
        self.modified = False
        self._update_title()
        self.view.fit()
        if problems:
            QMessageBox.warning(self, APP_NAME, "Some pictures could not be loaded:\n\n" + "\n".join(problems))

    def save_project(self) -> bool:
        if not self.project_path:
            return self.save_project_as()
        try:
            save_project(self.project_path, self.view.spec, self.view.layers)
        except Exception as exc:
            QMessageBox.warning(self, APP_NAME, f"Could not save the project:\n{exc}")
            return False
        self.modified = False
        self._update_title()
        self.statusBar().showMessage(f"Saved {self.project_path}", 4000)
        return True

    def save_project_as(self) -> bool:
        path, _ = QFileDialog.getSaveFileName(self, "Save project", self._dir("project"), PROJECT_FILTER)
        if not path:
            return False
        if not path.lower().endswith(".json"):
            path += ".cover.json"
        self._remember_dir("project", path)
        self.project_path = path
        return self.save_project()

    # --- export -----------------------------------------------------------

    def export(self) -> None:
        if not self.view.layers and QMessageBox.question(
                self, APP_NAME, "The cover is empty. Save a blank PDF anyway?") != QMessageBox.StandardButton.Yes:
            return
        low = [l.name for l in self.view.layers
               if (dpi := l.effective_dpi()) is not None and dpi < 300]
        if low and QMessageBox.question(
                self, APP_NAME, "These pictures are below 300 dpi at their current size and may print "
                "blurry:\n\n" + "\n".join(low) + "\n\nSave anyway?") != QMessageBox.StandardButton.Yes:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Save cover as PDF", self._dir("export"), "PDF (*.pdf)")
        if not path:
            return
        if not path.lower().endswith(".pdf"):
            path += ".pdf"
        self._remember_dir("export", path)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            export_pdf(path, self.view.spec, self.view.layers, self.panel.include_barcode.isChecked())
        except Exception as exc:
            QApplication.restoreOverrideCursor()
            QMessageBox.warning(self, APP_NAME, f"Could not save the PDF:\n{exc}")
            return
        QApplication.restoreOverrideCursor()
        s = self.view.spec
        self.statusBar().showMessage(f"Saved {path} ({s.full_width:.3f} × {s.full_height:.3f} in)", 8000)

    # --- help -------------------------------------------------------------

    def show_help(self) -> None:
        QMessageBox.information(self, "How to use", (
            "<b>Add pictures</b> with Ctrl+O or by dragging files onto the cover. "
            "PDF, PNG, JPG, WebP, BMP, GIF and TIFF all work.<br><br>"
            "<b>Move</b>: drag a picture. <b>Resize</b>: drag a handle — corners keep the "
            "ratio, edges stretch one side. Both snap to the guides and to other pictures; "
            "hold <b>Shift</b> while dragging to place freely. Arrow keys nudge by 0.01 in "
            "(Shift: 0.1 in).<br><br>"
            "<b>Exact sizes</b>: type X, Y, Width or Height in the panel and press Enter. "
            "With <i>Maintain ratio</i> on, the other side follows.<br><br>"
            "<b>Rulers</b> along the top and left measure inches from the cover's top-left "
            "corner. Above the scale, the <i>Cover</i> row shows the bleed, back, spine and "
            "front; <i>Safe</i> shows the margins and safe areas; <i>Picture</i> shows the "
            "selected picture. The guides and the selected picture's edges run on into the "
            "rulers. Hover any line or number for exact values; the Legend in the panel says "
            "which line is which.<br><br>"
            "<b>Zoom</b>: Ctrl+wheel, Ctrl+= / Ctrl+-, Ctrl+0 to fit. Pan with the middle "
            "mouse button or the scroll bars.<br><br>"
            "<b>Barcode</b>: the grey box on the back cover is a placeholder. It cannot be "
            "moved, stays above every picture, and is left out of the PDF unless you ask — "
            "Amazon prints the real barcode there, so keep important art out of it.<br><br>"
            "<b>Save as PDF</b> (Ctrl+E) writes one page at exactly the full cover size, "
            "bleed included, using the original files at full resolution."))

    # --- closing ----------------------------------------------------------

    def closeEvent(self, event) -> None:
        if not self._confirm_discard():
            event.ignore()
            return
        self.settings.setValue("window/geometry", self.saveGeometry())
        event.accept()


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv if argv is None else argv
    app = QApplication(argv)
    app.setApplicationName(APP_NAME)
    win = MainWindow()
    win.show()
    files = [a for a in argv[1:] if os.path.isfile(a)]
    projects = [f for f in files if f.lower().endswith(".json")]
    if projects:
        win.open_project(projects[0])
    pictures = [f for f in files if is_supported(f)]
    if pictures:
        win.add_files(pictures)
    return app.exec()
