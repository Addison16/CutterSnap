"""Command line.

  cuttersnap PHOTO OUT.stl [--box x,y,w,h] [--cookie x,y ...] [--not-cookie x,y ...]
  cuttersnap PHOTO OUT.stl --edge x,y --edge x,y --edge x,y ...
  cuttersnap PROJECT.json OUT.stl

A project file (saved from the web page or with --save-project) rebuilds the
exact same cutter from its stored outline; the photo is not needed.
"""
from __future__ import annotations

import argparse

import cv2
from shapely.geometry import Polygon
from shapely.ops import orient

from .cutter import CutterParams, build_cutter, build_pusher
from .livewire import edge_mask
from .outline import check_outline, mask_to_outline
from .project import Project, sha256_file
from .segment import segment


def _pt(s: str) -> tuple[int, int]:
    x, y = s.split(",")
    return int(x), int(y)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="cuttersnap", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("photo", help="cookie photo, or a .json project file")
    ap.add_argument("out", help="output .stl path")
    ap.add_argument("--box", help="x,y,w,h around the cookie, in photo pixels")
    ap.add_argument("--cookie", type=_pt, action="append", default=[], help="x,y on the cookie")
    ap.add_argument("--not-cookie", type=_pt, action="append", default=[], help="x,y off the cookie")
    ap.add_argument("--edge", type=_pt, action="append", default=[],
                    help="x,y on the cookie's edge; 3 or more, in order around it")
    ap.add_argument("--size", type=float, default=90.0, help="longest side in mm (default 90)")
    ap.add_argument("--nozzle", type=float, default=0.4, help="printer nozzle in mm (default 0.4)")
    ap.add_argument("--spread", type=float, default=0.0,
                    help="shrink the cutter by this many mm to undo dough spreading (default 0)")
    ap.add_argument("--preview", help="also write a JPEG of the photo with the traced outline")
    ap.add_argument("--save-project", help="also write a .json project file")
    ap.add_argument("--pusher", help="also write a pusher plate .stl (2 mm smaller, with a knob)")
    a = ap.parse_args(argv)

    if a.photo.lower().endswith(".json"):
        proj = Project.load(a.photo)
        poly = orient(Polygon(proj.outline_mm).buffer(0), 1.0)
    else:
        img = cv2.imread(a.photo)
        if img is None:
            ap.error(f"cannot read {a.photo}")
        if a.edge and len(a.edge) < 3:
            ap.error("give at least 3 --edge points")
        box = tuple(int(v) for v in a.box.split(",")) if a.box else None
        mask = edge_mask(img, a.edge) if a.edge else segment(img, box, a.cookie, a.not_cookie)
        outline = mask_to_outline(mask, a.size)
        poly = outline.polygon
        proj = Project(outline_mm=[[round(x, 3), round(y, 3)] for x, y in poly.exterior.coords[:-1]],
                       size_mm=a.size, photo_name=a.photo, photo_sha256=sha256_file(a.photo),
                       box=list(box) if box else None, cookie=[list(p) for p in a.cookie],
                       not_cookie=[list(p) for p in a.not_cookie], edge=[list(p) for p in a.edge],
                       nozzle_mm=a.nozzle, spread=a.spread)
        # build from the rounded outline, exactly as a reload of the project would
        poly = orient(Polygon(proj.outline_mm).buffer(0), 1.0)
        if a.preview:
            pts = outline.to_pixels().round().astype("int32").reshape(-1, 1, 2)
            cv2.polylines(img, [pts], True, (255, 0, 255), max(2, img.shape[1] // 300))
            cv2.imwrite(a.preview, img)

    params = CutterParams.for_nozzle(proj.nozzle_mm, height=proj.height,
                                     flange_w=proj.flange_w, spread=proj.spread)
    mesh = build_cutter(poly, params)
    mesh.export(a.out)
    if a.save_project:
        proj.save(a.save_project)
    if a.pusher:
        plate, notes = build_pusher(poly, params)
        plate.export(a.pusher)
        for n in notes:
            print(n)
    w, h, _ = mesh.extents
    c = check_outline(poly)
    print(f"{a.out}: {w:.1f} x {h:.1f} mm, watertight={mesh.is_watertight}, "
          f"tightest point radius {c['min_convex_radius_mm']} mm, "
          f"tightest notch radius {c['min_concave_radius_mm']} mm")


if __name__ == "__main__":
    main()
