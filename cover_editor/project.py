"""Save and reopen a layout as a small JSON file (*.cover.json).

The pictures are referenced, not copied. Each path is stored both relative to
the project file and absolute; on open the relative one is tried first, so a
folder holding the project and its pictures can be moved as a whole.
"""

from __future__ import annotations

import json
import os

from PySide6.QtCore import QRectF

from .layers import Layer, load_source
from .spec import PT_PER_IN, CoverSpec

FORMAT = 1


def save_project(path: str, spec: CoverSpec, layers: list[Layer]) -> None:
    base = os.path.dirname(os.path.abspath(path))
    entries = []
    for layer in layers:  # bottom to top
        r = layer.rect()
        src = os.path.abspath(layer.source.path)
        try:
            rel = os.path.relpath(src, base)
        except ValueError:  # another drive
            rel = None
        entries.append({
            "path": src, "relative": rel, "page": layer.source.page,
            "x": r.x() / PT_PER_IN, "y": r.y() / PT_PER_IN,
            "width": r.width() / PT_PER_IN, "height": r.height() / PT_PER_IN,
        })
    data = {"format": FORMAT, "units": "inches", "cover": spec.to_dict(), "layers": entries}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def load_project(path: str) -> tuple[CoverSpec, list[Layer], list[str]]:
    """Returns the spec, the layers that loaded, and messages for any that didn't."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    base = os.path.dirname(os.path.abspath(path))
    spec = CoverSpec.from_dict(data.get("cover", {}))
    layers, problems = [], []
    for e in data.get("layers", []):
        candidates = [os.path.join(base, e["relative"])] if e.get("relative") else []
        candidates.append(e["path"])
        found = next((c for c in candidates if os.path.exists(c)), None)
        if found is None:
            problems.append(f"Missing: {e['path']}")
            continue
        try:
            layer = Layer(load_source(found, int(e.get("page", 0))))
        except Exception as exc:  # unreadable file: skip it, keep the rest
            problems.append(f"{os.path.basename(found)}: {exc}")
            continue
        layer.set_rect(QRectF(e["x"] * PT_PER_IN, e["y"] * PT_PER_IN,
                              e["width"] * PT_PER_IN, e["height"] * PT_PER_IN))
        layers.append(layer)
    return spec, layers, problems
