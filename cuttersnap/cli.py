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

from .cutter import build_cutter, build_pusher, cutting_face, facet_error_mm
from .livewire import edge_mask
from .outline import check_outline, mask_to_outline
from .project import Project, sha256_file
from .segment import segment
from .stamp import StampParams, build_stamp, detail_lines, rings


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
    ap.add_argument("--halo", type=float, default=0.0,
                    help="grow the cutter by this many mm for a bubble border (default 0)")
    ap.add_argument("--initials", default="", help="up to 3 letters pressed into the underside of the base")
    ap.add_argument("--flip", action="store_true", help="mirror image, for the other one of a pair")
    ap.add_argument("--preview", help="also write a JPEG of the photo with the traced outline")
    ap.add_argument("--save-project", help="also write a .json project file")
    ap.add_argument("--pusher", help="also write a pusher plate .stl (2 mm smaller, with a knob)")
    ap.add_argument("--stamp", help="also write a matching stamp .stl with the icing lines raised")
    ap.add_argument("--stamp-detail", type=float, default=0.5,
                    help="0 to 1: higher finds fainter icing lines (default 0.5)")
    ap.add_argument("--stamp-depth", type=float, default=2.0,
                    help="how far the stamp's lines stand up, 1 to 4 mm (default 2)")
    a = ap.parse_args(argv)

    if a.photo.lower().endswith(".json"):
        proj = Project.load(a.photo)
        # options given on the command line change the saved settings
        for opt, key in (("halo", "halo"), ("initials", "text"), ("flip", "flip"), ("spread", "spread")):
            if getattr(a, opt):
                setattr(proj, key, getattr(a, opt))
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
        lines = detail_lines(img, outline, a.stamp_detail) if a.stamp else None
        proj = Project(outline_mm=[[round(x, 3), round(y, 3)] for x, y in poly.exterior.coords[:-1]],
                       size_mm=a.size, photo_name=a.photo, photo_sha256=sha256_file(a.photo),
                       box=list(box) if box else None, cookie=[list(p) for p in a.cookie],
                       not_cookie=[list(p) for p in a.not_cookie], edge=[list(p) for p in a.edge],
                       nozzle_mm=a.nozzle, spread=a.spread, halo=a.halo, text=a.initials,
                       flip=a.flip, stamp_lines_mm=rings(lines) if lines is not None else [],
                       stamp_depth=a.stamp_depth)
        if a.preview:
            pts = outline.to_pixels().round().astype("int32").reshape(-1, 1, 2)
            cv2.polylines(img, [pts], True, (255, 0, 255), max(2, img.shape[1] // 300))
            cv2.imwrite(a.preview, img)

    # build from the project's rounded outline, exactly as a reload of it would
    try:
        poly, params = proj.polygon(), proj.params()
    except ValueError as e:
        ap.error(str(e))
    notes: list[str] = []
    mesh = build_cutter(poly, params, notes)
    mesh.export(a.out)
    if a.save_project:
        proj.save(a.save_project)
    if a.stamp:
        if not proj.stamp_lines_mm:
            ap.error("this project has no stamp lines; make the stamp from the photo")
        build_stamp(poly, proj.stamp_lines(), params, StampParams(relief_h=proj.stamp_depth)).export(a.stamp)
    if a.pusher:
        plate, pnotes = build_pusher(poly, params)
        plate.export(a.pusher)
        notes += pnotes
    for n in notes:
        print(n)
    w, h, _ = mesh.extents
    c = check_outline(cutting_face(poly, params.spread, params.halo))
    print(f"{a.out}: {w:.1f} x {h:.1f} mm, watertight={mesh.is_watertight}, "
          f"tightest point radius {c['min_convex_radius_mm']} mm, "
          f"tightest notch radius {c['min_concave_radius_mm']} mm, "
          f"facets within {facet_error_mm(poly, params):.3f} mm of the curve")


if __name__ == "__main__":
    main()
