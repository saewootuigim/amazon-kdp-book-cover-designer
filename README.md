# Amazon KDP Book Cover Designer

A small Windows app for laying out a KDP paperback's full wrap-around cover
(back + spine + front, with bleed) and saving it as a print-ready PDF that you
can upload straight to Kindle Direct Publishing.

![platform](https://img.shields.io/badge/platform-Windows-blue) ![python](https://img.shields.io/badge/python-3.12-blue)

- Place pictures (PNG, JPG, PDF pages and more) on the cover by dragging or by typing exact inches.
- Trim, bleed, spine and safe-area guides match the KDP cover template, and everything snaps to them.
- Rulers along the top and left show the cover, safe-area and picture sizes.
- Exports one PDF page at the exact full-cover size. It is built from the original files, so nothing is resampled from the screen.

## Contents

- [Requirements](#requirements)
- [Install](#install)
- [Run](#run)
- [Quick start: make a cover in 6 steps](#quick-start-make-a-cover-in-6-steps)
- [Setting up the cover size](#setting-up-the-cover-size)
- [Placing and arranging pictures](#placing-and-arranging-pictures)
- [Guides, snapping and rulers](#guides-snapping-and-rulers)
- [Barcode area](#barcode-area)
- [Saving: projects and PDFs](#saving-projects-and-pdfs)
- [Uploading to KDP](#uploading-to-kdp)
- [Keyboard shortcuts](#keyboard-shortcuts)
- [Troubleshooting](#troubleshooting)
- [Tests](#tests)
- [Code layout](#code-layout)

## Requirements

- Windows 10 or 11
- [Python 3.12](https://www.python.org/downloads/). Tick *Add python.exe to PATH* or install the `py` launcher.
- About 300 MB of disk space for the local virtual environment

## Install

```bat
git clone https://github.com/saewootuigim/amazon-kdp-book-cover-designer.git
cd amazon-kdp-book-cover-designer
setup.bat
```

`setup.bat` creates a virtual environment in `.venv\` and installs the pinned
packages from `requirements.txt` (PySide6, PyMuPDF, Pillow). Everything stays
inside the project folder:

| What | Where |
|---|---|
| Virtual environment | `.venv\` |
| pip cache | `.pip-cache\` |
| pip config | `.venv\pip.ini` |
| App settings (last folders, window position) | `settings.ini`, not the registry |

To start over, delete `.venv\` and run `setup.bat` again. Deleting the project
folder removes everything the app installed.

## Run

Double-click **`run.bat`**. You can also drop picture files onto `run.bat`, or
pass them on the command line. They are added to a new cover:

```bat
run.bat front.png back.jpg
```

From a terminal you can also run it without `run.bat`:

```bat
.venv\Scripts\pythonw.exe main.py [files...]
```

## Quick start: make a cover in 6 steps

1. **Get your numbers from KDP.** Use KDP's cover calculator / template
   generator to find your trim size, page count and paper type.
2. **Set the cover size.** Type the trim width and height and the spine width
   into the **Cover** box in the panel, pressing Enter after each. Or open
   **Cover → Cover setup…** and let it work out the spine width from the page
   count (see [below](#setting-up-the-cover-size)). Check that the full cover
   size shown matches KDP's template.
3. **Add your artwork.** Click **Add picture…** (Ctrl+O), or drag files from
   Explorer onto the cover.
4. **Position it.** Drag pictures into place, using the corner handles to
   resize. They snap to the trim, spine, safe areas and centres. Art meant to
   reach the edge of the page should extend into the red-tinted bleed.
   Keep text inside the blue safe areas.
5. **Check resolution.** The panel shows each picture's print resolution at
   its current size and warns below 300 dpi.
6. **Export.** Click **Save as PDF…** (Ctrl+E). Also save the project
   (Ctrl+S) so you can come back and edit it.

## Setting up the cover size

The defaults match the KDP template for *The Legend of the Tweedy Sisters*:

| Setting | Default |
|---|---|
| Trim (page) size | 5.5 x 8.5 in |
| Spine width | 0.155 in |
| Bleed | 0.125 in |
| **Full cover** | **11.405 x 8.75 in** |

Full cover width = bleed + page width + spine + page width + bleed.
Full cover height = bleed + page height + bleed.

**Quick edit:** the **Cover** box in the panel has page width and height,
spine width, bleed, safe margin and spine margin. Type a value and press Enter.
It shows the resulting full cover size.

**Cover → Cover setup…** has every setting, including the barcode area, plus
a spine calculator. Enter the page count, pick the paper, and it fills in the
spine width using KDP's paperback formula (pages x thickness per page):

| Paper | Inches per page |
|---|---|
| White paper, black ink | 0.002252 |
| Cream paper, black ink | 0.0025 |
| White paper, standard colour | 0.002252 |
| White paper, premium colour | 0.002347 |

For example, 300 pages on cream paper gives 300 x 0.0025 = 0.75 in.

**Resizing an existing design:** when the cover changes size, pictures move
with the part they sit on:

- Back-cover art stays where it is.
- Front-cover art shifts with the front cover.
- A picture that exactly fills the spine is stretched to the new spine width.
- A full wrap-around picture is scaled, keeping its ratio, so it still covers
  everything.

The sizes are saved in the project file along with the layout.

## Placing and arranging pictures

**Supported formats:** PDF, PNG, JPG/JPEG, WebP, BMP, GIF, TIFF, TGA, ICO.
For a multi-page PDF you choose which page to place.

| To | Do |
|---|---|
| Add a picture | **Add picture…** / Ctrl+O, or drag files onto the cover. |
| Select | Click it. Esc deselects. |
| Move | Drag it. Arrow keys nudge 0.01 in (Shift: 0.1 in). |
| Resize, keeping the ratio | Drag a **corner** handle. |
| Stretch one side | Drag an **edge** handle. |
| Place freely | Hold **Shift** while dragging or resizing to turn snapping off. |
| Exact size or position | Type X, Y, Width or Height (inches, from the cover's top-left corner) in the panel and press Enter. With **Maintain ratio** on, the other side follows. |
| Layer order | **Arrange** menu, or Ctrl+] / Ctrl+[ for forward / backward, Ctrl+Shift+] / Ctrl+Shift+[ for front / back. |
| Delete | Delete or Backspace, or **Arrange → Delete picture**. |
| Zoom | Ctrl+wheel, Ctrl+= / Ctrl+-, Ctrl+0 to fit, Ctrl+1 for actual size. |
| Pan | Drag with the middle mouse button. |

**Typical layouts**

- *One wrap-around image:* add it, then drag its corners until it covers the
  whole cover including the bleed on every side.
- *Separate front and back art:* place the front image so its left edge snaps
  to the right spine edge and its right edge reaches the outer bleed. Place the
  back image the same way on the other side. Add a spine image (or a solid
  colour image) snapped to both spine edges.
- *Title and author text:* make them as transparent PNGs, or as a PDF exported
  from Word, Affinity or Inkscape so they stay vector. Then place them inside
  the safe areas.

## Guides, snapping and rulers

Moving and resizing snap to the guides and to the edges and centres of the
other pictures. The guides are:

- **Trim line**: red dashes. Everything outside it, the red-tinted bleed, is
  cut off when the book is printed.
- **Spine edges**: solid lines.
- **Safe areas**: blue dashes, with the spine's safe area in blue dots. Keep
  text and important details inside them.
- **Centres** of the back, spine, front and the cover's height: green dots.

The **Legend** box at the bottom of the panel shows which line is which.
Hover over a guide on the cover to see its name and position.

**Rulers** run along the top and left. Each has a scale in inches, measured
from the cover's top-left corner like the X and Y fields. Above the scale are
three rows of dimension lines:

- **Cover**: bleed, back cover, spine and front cover (0.125 | 5.5 | 0.155 | 5.5 | 0.125).
- **Safe**: the margins and safe areas, including the spine's 0.062 | 0.031 | 0.062.
- **Picture**: the selected picture's width (top ruler) or height (left ruler).

The guides and the selected picture's edges continue into the rulers. Numbers
too wide for their gap, such as the spine's, sit in boxes centred on it. Zoom
in to see the spine's lines separate. Hover any number or line on a ruler for
its exact start, end and size.

## Barcode area

The **barcode placeholder** sits on the back cover, 2 x 1.2 in, 0.25 in in from
the right and bottom edges of the back cover's safe area, as on the KDP
template. That puts it 0.25 in from the spine and 0.375 in above the bottom
trim edge. It always sits above every picture and cannot be moved. Its size
and position can be changed in **Cover → Cover setup…**.

KDP prints the real barcode there, so keep important art out of it. It is
left out of the PDF unless you tick *Include barcode placeholder in PDF*.

## Saving: projects and PDFs

**Project** (File → Save project, Ctrl+S, or Save project as…, Ctrl+Shift+S)
writes a small `.cover.json` file with the cover sizes and every picture's
position, size and layer order. It **references** the picture files rather
than copying them, so keep the pictures where they are, or move them together
with the project. Open it again with File → Open project… (Ctrl+Shift+O).

**PDF** (Save as PDF…, Ctrl+E) writes one page at exactly the full cover size.
It is built from the original files, not the on-screen preview:

- JPEG and PNG files are embedded unchanged.
- Other image formats are converted to PNG without loss.
- A placed PDF page stays vector, so text and line art stay sharp.

## Uploading to KDP

1. In your KDP paperback's **Paperback Content** page, under *Book Cover*,
   choose **Upload a cover you already have (print-ready PDF only)**.
2. Upload the exported PDF.
3. Open the **Launch Previewer** and check that nothing important crosses the
   trim or spine lines.

If KDP rejects the size, compare the full cover size in the panel with KDP's
template. The usual causes are a wrong page count or paper type in the spine
calculation, or a changed bleed.

## Keyboard shortcuts

| Shortcut | Action |
|---|---|
| Ctrl+N | New cover |
| Ctrl+Shift+O | Open project |
| Ctrl+S / Ctrl+Shift+S | Save project / Save project as |
| Ctrl+O | Add picture |
| Ctrl+E | Save as PDF |
| Arrow keys (Shift) | Nudge selected picture 0.01 in (0.1 in) |
| Delete / Backspace | Delete selected picture |
| Esc | Deselect |
| Ctrl+] / Ctrl+[ | Bring forward / Send backward |
| Ctrl+Shift+] / Ctrl+Shift+[ | Bring to front / Send to back |
| Ctrl+= / Ctrl+- / Ctrl+wheel | Zoom in / out |
| Ctrl+0 / Ctrl+1 | Fit cover / Actual size |
| Shift while dragging | Turn snapping off |
| Middle mouse drag | Pan |
| F1 | How to use |

## Troubleshooting

| Problem | Fix |
|---|---|
| `run.bat` says the virtual environment is missing | Run `setup.bat`. |
| `setup.bat` fails to create the environment | Install Python 3.12 and make sure `py -3.12` or `python` works in a terminal. |
| Nothing happens when `run.bat` starts | Run `.venv\Scripts\python.exe main.py` in a terminal to see the error. |
| A picture is missing after opening a project | Projects reference picture files by path. Put the file back, or add it again. |
| Low-dpi warning | Use a larger source image, or make the picture smaller on the cover. KDP recommends 300 dpi. |
| Window opens off-screen | Delete `settings.ini`. It only stores the window position and last-used folders. |

## Tests

```bat
.venv\Scripts\python.exe tests\smoke.py
```

This drives the real window headless. It covers loading every format,
dragging, Shift, corner and edge resizing with snapping, typed sizes, layer
order, the barcode, PDF export and project round-trips. Output goes to
`tests\out\`, which git ignores.

## Code layout

```
main.py                 entry point (run.bat calls it)
setup.bat               creates .venv and installs requirements
run.bat                 launches the app with .venv\Scripts\pythonw.exe
requirements.txt        pinned dependencies
cover_editor/
  spec.py               cover geometry and guides (inches)
  layers.py             picture loading, Layer and the barcode item
  canvas.py             the view: mouse, snapping, guides and handles
  rulers.py             the rulers and their dimension rows
  panel.py              the tool panel
  setup_dialog.py       cover setup / spine calculator
  export.py             PDF writer (PyMuPDF)
  project.py            .cover.json save/load
  app.py                main window and menus
tests/
  smoke.py              headless end-to-end test
```

Built with [PySide6](https://doc.qt.io/qtforpython-6/) (Qt),
[PyMuPDF](https://pymupdf.readthedocs.io/) and
[Pillow](https://python-pillow.org/). Versions are pinned in
`requirements.txt`.

## License

GNU General Public License v3.0. See [LICENSE](LICENSE).
