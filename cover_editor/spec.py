"""Cover geometry.

Every length in `CoverSpec` is in inches, because that is how KDP states them.
The canvas and the exported PDF both work in PostScript points (72 per inch),
so a scene coordinate is already a PDF coordinate and export needs no maths.

Layout, left to right, for a paperback's full wrap-around cover:

    | bleed | back cover (trim) | spine | front cover (trim) | bleed |

with `bleed` above and below as well. The defaults are the numbers from KDP's
template for this book: 5.5 x 8.5 in trim, 0.155 in spine, full cover
11.405 x 8.75 in.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from typing import NamedTuple

PT_PER_IN = 72.0

# Inches per page, from KDP's spine-width formula (pages x thickness).
PAPER_THICKNESS = {
    "White paper, black ink": 0.002252,
    "Cream paper, black ink": 0.0025,
    "White paper, standard colour": 0.002252,
    "White paper, premium colour": 0.002347,
}


class Rect(NamedTuple):
    x: float
    y: float
    w: float
    h: float

    @property
    def right(self) -> float:
        return self.x + self.w

    @property
    def bottom(self) -> float:
        return self.y + self.h

    @property
    def cx(self) -> float:
        return self.x + self.w / 2

    @property
    def cy(self) -> float:
        return self.y + self.h / 2

    def pt(self) -> "Rect":
        return Rect(*(v * PT_PER_IN for v in self))


class Guide(NamedTuple):
    vertical: bool
    pos: float  # inches from the left (vertical) or top (horizontal) edge
    kind: str  # edge | trim | spine | safe | spine-safe | center | barcode
    visible: bool  # barcode guides snap but are not drawn; the box shows them


@dataclass
class CoverSpec:
    trim_width: float = 5.5
    trim_height: float = 8.5
    spine_width: float = 0.155
    bleed: float = 0.125
    margin: float = 0.125
    spine_margin: float = 0.062
    barcode_width: float = 2.0
    barcode_height: float = 1.2
    barcode_margin: float = 0.25

    # --- derived sizes ---------------------------------------------------

    @property
    def full_width(self) -> float:
        return 2 * self.bleed + 2 * self.trim_width + self.spine_width

    @property
    def full_height(self) -> float:
        return 2 * self.bleed + self.trim_height

    def full(self) -> Rect:
        return Rect(0, 0, self.full_width, self.full_height)

    def trim(self) -> Rect:
        """Everything that survives the cut: back, spine and front together."""
        b = self.bleed
        return Rect(b, b, self.full_width - 2 * b, self.trim_height)

    def back(self) -> Rect:
        return Rect(self.bleed, self.bleed, self.trim_width, self.trim_height)

    def spine(self) -> Rect:
        return Rect(self.bleed + self.trim_width, self.bleed, self.spine_width, self.trim_height)

    def front(self) -> Rect:
        x = self.bleed + self.trim_width + self.spine_width
        return Rect(x, self.bleed, self.trim_width, self.trim_height)

    # The safe areas lose `margin` on the outer edge, top and bottom, but not on
    # the spine side, where the spine margin applies instead. That is what makes
    # KDP's "Safe Area" 5.375 x 8.25 for a 5.5 x 8.5 trim.

    def back_safe(self) -> Rect:
        b = self.back()
        return Rect(b.x + self.margin, b.y + self.margin, b.w - self.margin, b.h - 2 * self.margin)

    def front_safe(self) -> Rect:
        f = self.front()
        return Rect(f.x, f.y + self.margin, f.w - self.margin, f.h - 2 * self.margin)

    def spine_safe(self) -> Rect:
        s = self.spine()
        w = max(s.w - 2 * self.spine_margin, 0.0)
        return Rect(s.x + self.spine_margin, s.y + self.margin, w, s.h - 2 * self.margin)

    def barcode(self) -> Rect:
        """Bottom-right of the back cover, `barcode_margin` in from the right and
        bottom borders of the back safe area — where KDP prints the real one."""
        safe = self.back_safe()
        right = safe.right - self.barcode_margin
        bottom = safe.bottom - self.barcode_margin
        return Rect(right - self.barcode_width, bottom - self.barcode_height,
                    self.barcode_width, self.barcode_height)

    # --- guides ------------------------------------------------------------

    def guides(self) -> list[Guide]:
        full, back, spine, front = self.full(), self.back(), self.spine(), self.front()
        bs, fs, ss, bc = self.back_safe(), self.front_safe(), self.spine_safe(), self.barcode()

        # Listed in priority order: where two coincide, the first one's kind wins.
        raw = [
            (True, 0, "edge"), (True, full.w, "edge"),
            (False, 0, "edge"), (False, full.h, "edge"),
            (True, back.x, "trim"), (True, front.right, "trim"),
            (False, back.y, "trim"), (False, back.bottom, "trim"),
            (True, spine.x, "spine"), (True, spine.right, "spine"),
            (True, bs.x, "safe"), (True, fs.right, "safe"),
            (False, bs.y, "safe"), (False, bs.bottom, "safe"),
            (True, ss.x, "spine-safe"), (True, ss.right, "spine-safe"),
            (True, back.cx, "center"), (True, spine.cx, "center"), (True, front.cx, "center"),
            (False, full.h / 2, "center"),
            (True, bc.x, "barcode"), (True, bc.right, "barcode"),
            (False, bc.y, "barcode"), (False, bc.bottom, "barcode"),
        ]
        seen: set[tuple[bool, float]] = set()
        out: list[Guide] = []
        for vertical, pos, kind in raw:
            key = (vertical, round(pos, 6))
            if key in seen:
                continue
            seen.add(key)
            out.append(Guide(vertical, pos, kind, kind != "barcode"))
        return out

    # --- persistence -------------------------------------------------------

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "CoverSpec":
        names = {f.name for f in fields(cls)}
        return cls(**{k: float(v) for k, v in data.items() if k in names})
