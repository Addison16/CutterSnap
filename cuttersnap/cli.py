"""Command line: cuttersnap PHOTO OUT.stl [--box x,y,w,h] [--cookie x,y ...] [--not-cookie x,y ...]"""
from __future__ import annotations

import argparse

import cv2

from .cutter import CutterParams, build_cutter
from .outline import check_outline, mask_to_outline
from .segment import segment


def _pt(s: str) -> tuple[int, int]:
    x, y = s.split(",")
    return int(x), int(y)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="cuttersnap", description=__doc__)
    ap.add_argument("photo")
    ap.add_argument("out", help="output .stl path")
    ap.add_argument("--box", help="x,y,w,h around the cookie, in photo pixels")
    ap.add_argument("--cookie", type=_pt, action="append", default=[], help="x,y on the cookie")
    ap.add_argument("--not-cookie", type=_pt, action="append", default=[], help="x,y off the cookie")
    ap.add_argument("--size", type=float, default=90.0, help="longest side in mm (default 90)")
    ap.add_argument("--nozzle", type=float, default=0.4, help="printer nozzle in mm (default 0.4)")
    ap.add_argument("--spread", type=float, default=0.0,
                    help="shrink the cutter by this many mm to undo dough spreading (default 0)")
    ap.add_argument("--preview", help="also write a JPEG of the photo with the traced outline")
    a = ap.parse_args(argv)

    img = cv2.imread(a.photo)
    if img is None:
        ap.error(f"cannot read {a.photo}")
    box = tuple(int(v) for v in a.box.split(",")) if a.box else None
    mask = segment(img, box, a.cookie, a.not_cookie)
    outline = mask_to_outline(mask, a.size)
    mesh = build_cutter(outline.polygon, CutterParams.for_nozzle(a.nozzle, spread=a.spread))
    mesh.export(a.out)
    if a.preview:
        pts = outline.to_pixels().round().astype("int32").reshape(-1, 1, 2)
        cv2.polylines(img, [pts], True, (255, 0, 255), max(2, img.shape[1] // 300))
        cv2.imwrite(a.preview, img)
    w, h, _ = mesh.extents
    c = check_outline(outline.polygon)
    print(f"{a.out}: {w:.1f} x {h:.1f} mm, watertight={mesh.is_watertight}, "
          f"tightest point radius {c['min_convex_radius_mm']} mm, "
          f"tightest notch radius {c['min_concave_radius_mm']} mm")


if __name__ == "__main__":
    main()
