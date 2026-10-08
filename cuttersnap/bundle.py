"""Size sets: the same cookie at several sizes, zipped with a print card."""
from __future__ import annotations

import io
import zipfile

from shapely.geometry import Polygon

from .cutter import CutterParams, build_cutter, build_pusher
from .outline import resize

SET_SIZES = (50.0, 75.0, 100.0)  # Mini 5 cm, Standard 7.5 cm, Large 10 cm


def print_card(p: CutterParams, nozzle_mm: float) -> str:
    """Slicer settings and care notes that go with every size set."""
    return f"""CutterSnap print card
=====================

Slicer
- Nozzle {nozzle_mm} mm, line width {nozzle_mm} to {nozzle_mm * 1.25:.2f} mm. The cutting edge is
  {p.wall_tip} mm (two lines) and the wall {p.wall_base} mm (four lines).
- Thin walls / Arachne can stay on or off: both were tested to print the edge as two
  full lines in PrusaSlicer.
- Base down, no supports, no brim. 0.2 mm layers are fine.
- Seam on the outside or random, not on a sharp point of the blade.
- PETG lasts longer than PLA.

Pieces
- cutter-*.stl: built as a mirror image, because you turn it over to cut; the cookie
  comes out the same way round as the photo.
- pusher-*.stl: press it down through the cutter to push out dough that sticks.

Care
- Not food-safe in any certified sense: layer lines hold on to dough.
- Wash by hand in warm, not hot, water and dry right away. PLA softens around 50 C,
  so keep it out of the dishwasher and hot cars.
- Dust the blade with flour. Replace the cutter when its edge gets rough.
"""


def size_set(outline: Polygon, p: CutterParams, nozzle_mm: float,
             sizes=SET_SIZES) -> tuple[bytes, list[str]]:
    """Zip of a cutter and pusher at each size, plus the print card.

    Each size is rounded to the corner rules again, so small sizes keep the
    same minimum radii as the original.
    """
    notes: list[str] = []
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for size in sizes:
            name = f"{size / 10:g}cm"
            poly = resize(outline, size)
            cut_notes: list[str] = []
            z.writestr(f"cutter-{name}.stl", build_cutter(poly, p, cut_notes).export(file_type="stl"))
            notes += [f"{name}: {n}" for n in cut_notes]
            try:
                plate, pnotes = build_pusher(poly, p)
                z.writestr(f"pusher-{name}.stl", plate.export(file_type="stl"))
            except ValueError as e:
                notes.append(f"{name}: no pusher ({e}).")
        z.writestr("PRINT-CARD.txt", print_card(p, nozzle_mm))
    return buf.getvalue(), notes
