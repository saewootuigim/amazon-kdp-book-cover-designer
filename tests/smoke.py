"""Headless end-to-end check. Run: .venv\\Scripts\\python.exe tests\\smoke.py

Builds test pictures in every supported format, drives the real window with
synthetic mouse and key events (move, resize, snapping, Shift, typed sizes,
layer order), exports a PDF and checks its size and contents. Writes into
tests/out/, which is gitignored.
"""

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import pymupdf as fitz  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402
from PySide6.QtCore import QEvent, QPoint, QPointF, QRectF, Qt  # noqa: E402
from PySide6.QtGui import QMouseEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from cover_editor.app import MainWindow  # noqa: E402
from cover_editor.export import export_pdf  # noqa: E402
from cover_editor.project import load_project, save_project  # noqa: E402
from cover_editor.spec import PT_PER_IN, CoverSpec  # noqa: E402

OUT = os.path.join(ROOT, "tests", "out")
os.makedirs(OUT, exist_ok=True)
failures = []


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        failures.append(msg)


def close(a, b, tol=0.01):
    return abs(a - b) <= tol


# --- test pictures ----------------------------------------------------------
def make_pictures():
    paths = {}
    im = Image.new("RGB", (1500, 1000), (40, 90, 160))
    ImageDraw.Draw(im).ellipse((300, 200, 1200, 800), fill=(240, 200, 60))
    for ext in ("png", "jpg", "webp", "bmp", "gif", "tiff"):
        p = os.path.join(OUT, f"pic.{ext}")
        im.save(p)
        paths[ext] = p
    rgba = Image.new("RGBA", (600, 600), (0, 0, 0, 0))
    ImageDraw.Draw(rgba).rectangle((100, 100, 500, 500), fill=(200, 30, 30, 255))
    paths["rgba"] = os.path.join(OUT, "alpha.png")
    rgba.save(paths["rgba"])
    doc = fitz.open()
    for i in range(2):
        pg = doc.new_page(width=300, height=400)
        pg.insert_text((40, 200), f"Vector page {i + 1}", fontsize=24)
        pg.draw_rect(fitz.Rect(20, 20, 280, 380), color=(0, 0.5, 0), width=3)
    paths["pdf"] = os.path.join(OUT, "doc.pdf")
    doc.save(paths["pdf"])
    return paths


def mouse(view, kind, scene_pt, button=Qt.MouseButton.LeftButton, mods=Qt.KeyboardModifier.NoModifier):
    vp = QPointF(view.mapFromScene(scene_pt))
    gp = QPointF(view.viewport().mapToGlobal(vp.toPoint()))
    types = {"press": QEvent.Type.MouseButtonPress, "move": QEvent.Type.MouseMove,
             "release": QEvent.Type.MouseButtonRelease}
    buttons = button if kind != "release" else Qt.MouseButton.NoButton
    ev = QMouseEvent(types[kind], vp, gp, button if kind != "move" else Qt.MouseButton.NoButton,
                     buttons, mods)
    {"press": view.mousePressEvent, "move": view.mouseMoveEvent,
     "release": view.mouseReleaseEvent}[kind](ev)


def drag(view, a, b, mods=Qt.KeyboardModifier.NoModifier, steps=6):
    mouse(view, "press", a, mods=mods)
    for i in range(1, steps + 1):
        t = i / steps
        mouse(view, "move", QPointF(a.x() + (b.x() - a.x()) * t, a.y() + (b.y() - a.y()) * t), mods=mods)
    mouse(view, "release", b, mods=mods)


def main():
    app = QApplication(sys.argv)
    paths = make_pictures()
    win = MainWindow()
    win.resize(1400, 900)
    win.show()
    app.processEvents()
    view, panel = win.view, win.panel
    spec = view.spec

    print("geometry")
    check(close(spec.full_width, 11.405, 1e-9) and close(spec.full_height, 8.75, 1e-9), "full cover 11.405 x 8.75")
    check(close(spec.back_safe().w, 5.375, 1e-9) and close(spec.back_safe().h, 8.25, 1e-9), "safe area 5.375 x 8.25")
    check(close(spec.spine_safe().w, 0.031, 1e-9), "spine safe 0.031 (KDP rounds to 0.03)")

    print("loading")
    for key in ("png", "jpg", "webp", "bmp", "gif", "tiff", "rgba"):
        win.add_files([paths[key]])
    check(len(view.layers) == 7, "7 image formats loaded")
    first = view.layers[0]
    check(close(first.rect().width() / PT_PER_IN, 5.0) and close(first.rect().height() / PT_PER_IN, 1000 / 300),
          "image starts at 300 dpi size (1500 px -> 5 in)")
    view.clear_layers()
    # A 2-page PDF opens a page chooser, which would block headless; load page 2 directly.
    from cover_editor.layers import Layer, load_source
    bg = Layer(load_source(paths["png"]))
    view.add_layer(bg)
    pdf_layer = Layer(load_source(paths["pdf"], 1))
    view.add_layer(pdf_layer)
    check(pdf_layer.source.page == 1 and close(pdf_layer.rect().width(), 300), "PDF page 2 placed at its own size")
    app.processEvents()

    print("move + snap")
    view.select(bg)
    r0 = bg.rect()
    # Drag so the left edge lands 0.03 in from the back cover's safe line.
    target = spec.back_safe().x * PT_PER_IN
    press = QPointF(r0.left() + 12, r0.top() + 12)  # a corner the PDF layer above doesn't cover
    dx = target + 0.03 * PT_PER_IN - r0.left()
    s = view.transform().m11()
    check(0.03 * PT_PER_IN * s < 8, f"test offset is inside the snap distance ({0.03 * PT_PER_IN * s:.1f} px)")
    drag(view, press, QPointF(press.x() + dx, press.y()))
    check(close(bg.rect().left(), target, 0.001), "left edge snapped onto the safe line")
    view.set_layer_rect(bg, r0)
    drag(view, press, QPointF(press.x() + dx, press.y()), mods=Qt.KeyboardModifier.ShiftModifier)
    check(close(bg.rect().left(), target + 0.03 * PT_PER_IN, 1 / view._scale()), "Shift: no snapping")

    print("resize")
    view.set_layer_rect(bg, r0)
    ratio = r0.width() / r0.height()
    corner = r0.bottomRight()
    drag(view, corner, QPointF(corner.x() + 50, corner.y() + 10), mods=Qt.KeyboardModifier.ShiftModifier)
    r = bg.rect()
    check(close(r.width() / r.height(), ratio, 1e-6), "corner keeps the ratio")
    check(close(r.left(), r0.left(), 1e-6) and close(r.top(), r0.top(), 1e-6), "corner resize anchors the opposite corner")
    view.set_layer_rect(bg, r0)
    edge = QPointF(r0.right(), r0.center().y())
    drag(view, edge, QPointF(edge.x() + 40, edge.y() + 30), mods=Qt.KeyboardModifier.ShiftModifier)
    r = bg.rect()
    check(close(r.width(), r0.width() + 40, 1 / view._scale()) and close(r.height(), r0.height(), 1e-6), "edge stretches one side only")
    view.set_layer_rect(bg, r0)
    spine_x = spec.spine().x * PT_PER_IN
    edge = QPointF(r0.right(), r0.center().y())
    drag(view, edge, QPointF(spine_x + 0.02 * PT_PER_IN, edge.y()))
    check(close(bg.rect().right(), spine_x, 0.001), "edge resize snaps to the spine")
    view.set_layer_rect(bg, r0)
    corner = r0.bottomRight()
    # Aim so the horizontal pull dominates: the y it implies is a little short.
    s_aim = (spine_x - 0.02 * PT_PER_IN - r0.left()) / r0.width()
    drag(view, corner, QPointF(spine_x - 0.02 * PT_PER_IN, r0.top() + r0.height() * s_aim - 4))
    r = bg.rect()
    check(close(r.right(), spine_x, 0.001) and close(r.width() / r.height(), ratio, 1e-6),
          "corner resize snaps and keeps the ratio")

    print("barcode")
    b = view.barcode.rect()
    check(view.barcode.zValue() > max(l.zValue() for l in view.layers), "barcode above every layer")
    view.select(None)
    mouse(view, "press", b.center())
    mouse(view, "move", b.center() + QPointF(30, 30))
    mouse(view, "release", b.center() + QPointF(30, 30))
    check(view.barcode.rect() == b and view.selected is None, "barcode cannot be moved or selected")
    bc = spec.barcode()
    safe = spec.back_safe()
    check(close(bc.right, safe.right - 0.25, 1e-9) and close(bc.bottom, safe.bottom - 0.25, 1e-9),
          "barcode 0.25 in from the back safe area's right and bottom borders")
    check(close(bc.right, spec.spine().x - 0.25, 1e-9) and close(bc.bottom, 8.75 - 0.125 - 0.125 - 0.25, 1e-9),
          "that is 0.25 in from the spine and 0.375 in above the bottom trim")

    print("typed sizes")
    view.select(bg)
    view.set_layer_rect(bg, r0)
    panel.keep_ratio.setChecked(True)
    panel.fields["w"].setText("4")
    panel._field_edited("w")
    r = bg.rect()
    check(close(r.width() / PT_PER_IN, 4) and close(r.width() / r.height(), ratio, 1e-6), "width typed, ratio kept")
    panel.keep_ratio.setChecked(False)
    panel.fields["h"].setText("2")
    panel._field_edited("h")
    r = bg.rect()
    check(close(r.width() / PT_PER_IN, 4) and close(r.height() / PT_PER_IN, 2), "height typed, ratio free")
    panel.fields["x"].setText("1.5")
    panel._field_edited("x")
    check(close(bg.rect().x() / PT_PER_IN, 1.5), "X typed")
    check(panel.fields["w"].text() == "4.000", "fields show the new size")

    print("layer order")
    view.select(bg)
    view.reorder(bg, "top")
    check(view.layers[-1] is bg, "bring to front")
    view.reorder(bg, "down")
    check(view.layers[0] is bg, "send backward")
    view.reorder(bg, "up")
    check(view.layers[-1] is bg, "bring forward")
    view.reorder(bg, "bottom")
    check(view.layers[0] is bg and bg.zValue() < pdf_layer.zValue(), "send to back")
    check(panel.layer_list.item(0).text() == pdf_layer.name, "layer list shows top first")

    print("export")
    panel.fill_btn.click()
    r = bg.rect()
    page = view.page_rect()
    check(r.left() <= 0.001 and r.top() <= 0.001 and r.right() >= page.width() - 0.001
          and r.bottom() >= page.height() - 0.001, "fill covers the whole page")
    view.set_layer_rect(pdf_layer, pdf_layer.rect().translated(200, 0))
    out = os.path.join(OUT, "cover.pdf")
    export_pdf(out, spec, view.layers, include_barcode=False)
    with fitz.open(out) as d:
        pg = d[0]
        check(d.page_count == 1, "one page")
        check(close(pg.rect.width / 72, 11.405, 1e-4) and close(pg.rect.height / 72, 8.75, 1e-4),
              f"page is {pg.rect.width / 72:.3f} x {pg.rect.height / 72:.3f} in")
        check("Vector page 2" in pg.get_text(), "placed PDF stays vector (its text is extractable)")
        imgs = pg.get_images()
        check(len(imgs) == 1 and d.extract_image(imgs[0][0])["width"] == 1500, "image embedded at full 1500 px")
        check("BARCODE" not in pg.get_text(), "barcode left out by default")
        pg.get_pixmap(dpi=60).save(os.path.join(OUT, "cover-preview.png"))
    export_pdf(out, spec, view.layers, include_barcode=True)
    with fitz.open(out) as d:
        check("BARCODE PLACEHOLDER" in d[0].get_text(), "barcode included when asked")

    print("project")
    proj = os.path.join(OUT, "test.cover.json")
    save_project(proj, spec, view.layers)
    spec2, layers2, problems = load_project(proj)
    check(not problems and len(layers2) == 2, "project reloads both layers")
    check(all(close(a.rect().x(), b.rect().x(), 1e-6) and close(a.rect().width(), b.rect().width(), 1e-6)
              for a, b in zip(view.layers, layers2)), "positions and sizes round-trip")
    check(layers2[1].source.page == 1, "PDF page number round-trips")

    print("rulers")
    from cover_editor.rulers import dimension_rows
    cover, safe, pic = dimension_rows(spec, (1.0, 3.5), True)
    widths = [round(x.b - x.a, 4) for x in cover]
    check(widths == [0.125, 5.5, 0.155, 5.5, 0.125], f"top ruler cover row {widths}")
    widths = [round(x.b - x.a, 4) for x in safe]
    check(widths == [0.125, 5.375, 0.062, 0.031, 0.062, 5.375, 0.125], f"top ruler safe row {widths}")
    check(len(pic) == 1 and close(pic[0].b - pic[0].a, 2.5, 1e-9), "picture row shows the selected width")
    cover, safe, _ = dimension_rows(spec, None, False)
    check([round(x.b - x.a, 4) for x in cover] == [0.125, 8.5, 0.125]
          and [round(x.b - x.a, 4) for x in safe] == [0.125, 8.25, 0.125], "left ruler rows")
    app.processEvents()
    top, left = win.top_ruler, win.left_ruler
    for v in (0.0, spec.spine().x, spec.full_width):
        vp = view.mapFromScene(QPointF(v * PT_PER_IN, 0))
        g = view.viewport().mapToGlobal(vp)
        check(abs(top._u(v) - top.mapFromGlobal(g).x()) <= 1, f"top ruler lines up with the cover at x={v:.3f}")
    for v in (0.0, spec.full_height):
        vp = view.mapFromScene(QPointF(0, v * PT_PER_IN))
        g = view.viewport().mapToGlobal(vp)
        check(abs(left.height() - left._u(v) - left.mapFromGlobal(g).y()) <= 1,
              f"left ruler lines up with the cover at y={v:.3f}")

    print("typed cover sizes")
    view.clear_layers()
    back_pic = Layer(load_source(paths["png"]))
    front_pic = Layer(load_source(paths["png"]))
    spine_pic = Layer(load_source(paths["png"]))
    wrap_pic = Layer(load_source(paths["png"]))
    for layer in (wrap_pic, back_pic, front_pic, spine_pic):
        view.add_layer(layer)
    sp = spec.spine().pt()
    view.set_layer_rect(back_pic, QRectF(72, 72, 144, 96))
    view.set_layer_rect(front_pic, QRectF(spec.front().x * 72 + 36, 400, 144, 96))
    view.set_layer_rect(spine_pic, QRectF(sp.x, 0, sp.w, view.page_rect().height()))
    view.select(wrap_pic)
    panel.fill_btn.click()
    before = {id(l): l.rect() for l in view.layers}
    check(panel.cover_fields["spine_width"].text() == "0.155", "spine field shows 0.155")
    panel.cover_fields["spine_width"].setText("0.162")
    panel._cover_edited("spine_width")
    s2 = view.spec
    check(close(s2.spine_width, 0.162, 1e-9) and close(s2.full_width, 11.412, 1e-9), "spine 0.162 -> full cover 11.412")
    check("11.412" in panel.cover_labels["full"].text(), "full cover label updated")
    check(close(view.page_rect().width() / 72, 11.412, 1e-9), "page widened")
    check(close(view.barcode.rect().right() / 72, s2.spine().x - 0.25, 1e-9), "barcode still 0.25 in from the spine")
    check(back_pic.rect() == before[id(back_pic)], "back-cover picture stays put")
    check(close(front_pic.rect().x() - before[id(front_pic)].x(), 0.007 * 72, 1e-6), "front-cover picture moves 0.007 in")
    sp2 = s2.spine().pt()
    check(close(spine_pic.rect().x(), sp2.x, 1e-6) and close(spine_pic.rect().width(), sp2.w, 1e-6),
          "spine picture stretched to the new spine")
    w = wrap_pic.rect()
    check(w.left() <= 1e-6 and w.right() >= view.page_rect().width() - 1e-6
          and close(w.width() / w.height(), before[id(wrap_pic)].width() / before[id(wrap_pic)].height(), 1e-9),
          "full-cover picture still covers, same ratio")
    panel.cover_fields["trim_width"].setText("6")
    panel._cover_edited("trim_width")
    panel.cover_fields["trim_height"].setText("9")
    panel._cover_edited("trim_height")
    check(close(view.spec.full_width, 12.412, 1e-9) and close(view.spec.full_height, 9.25, 1e-9),
          "page 6 x 9 -> full cover 12.412 x 9.25")
    panel.cover_fields["trim_height"].setText("0")
    panel._cover_edited("trim_height")
    check(close(view.spec.trim_height, 9, 1e-9) and panel.cover_fields["trim_height"].text() == "9",
          "zero height refused, field restored")

    print("cover setup")
    view.apply_spec(CoverSpec(spine_width=0.5))
    check(close(view.page_rect().width() / 72, 11.75), "wider spine widens the page")
    view.apply_spec(CoverSpec())

    win.view.fit()
    app.processEvents()
    win.grab().save(os.path.join(OUT, "window.png"))
    win.modified = False
    win.close()
    print(f"\n{'FAILED: ' + str(len(failures)) if failures else 'all checks passed'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
