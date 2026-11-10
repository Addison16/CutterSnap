"""Score photo tracing against known-good outlines.

  python -m cuttersnap.benchmark CASES.json --photos FOLDER

CASES.json lists cookies: the photo (by file name and sha256), the marks a
person would make (box, cookie / not-cookie clicks, edge points) and the
reference outline (a project file). Photos are looked up in FOLDER and
cases whose photo is missing are skipped, so third-party photos never need
to be in the repository.

The score is the overlap (intersection over union) of the traced outline
and the reference after both are scaled to the same longest side and
centred; 1.0 is a perfect match. References can be redesigned shapes, not
exact photo labels, so compare scores between versions, not against 1.0.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2
import numpy as np
from shapely import affinity
from shapely.geometry import Polygon

from .livewire import edge_mask
from .outline import mask_to_outline
from .project import Project, sha256_file
from .segment import segment


def _norm(p: Polygon, size: float = 80.0) -> Polygon:
    x0, y0, x1, y1 = p.bounds
    k = size / max(x1 - x0, y1 - y0)
    p = affinity.scale(p, k, k, origin=(0, 0))
    c = p.centroid
    return affinity.translate(p, -c.x, -c.y)


def overlap(a: Polygon, b: Polygon) -> float:
    """Best IoU of two outlines over small shifts after scaling and centring."""
    a, b = _norm(a), _norm(b)
    best = 0.0
    for dx in np.arange(-3, 3.01, 0.5):
        for dy in np.arange(-3, 3.01, 0.5):
            c = affinity.translate(b, dx, dy)
            best = max(best, a.intersection(c).area / a.union(c).area)
    return best


def trace(img: np.ndarray, case: dict) -> Polygon:
    pts = [tuple(p) for p in case.get("edge", [])]
    if len(pts) >= 3:
        mask = edge_mask(img, pts)
    else:
        mask = segment(img, tuple(case["box"]) if case.get("box") else None,
                       [tuple(p) for p in case.get("cookie", [])],
                       [tuple(p) for p in case.get("not_cookie", [])])
    return mask_to_outline(mask, 80.0).polygon


def run(cases_path: Path, photos: Path) -> list[dict]:
    spec = json.loads(cases_path.read_text())
    found = {}
    for f in photos.iterdir() if photos.is_dir() else []:
        if f.is_file():
            found[sha256_file(f)] = f
    rows = []
    for case in spec["cases"]:
        photo = found.get(case["photo_sha256"])
        if photo is None:
            rows.append({"name": case["name"], "score": None, "note": "photo not found"})
            continue
        ref = Project.load(cases_path.parent / case["reference"]).polygon()
        poly = trace(cv2.imread(str(photo)), case)
        rows.append({"name": case["name"], "score": round(overlap(ref, poly), 3)})
    return rows


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="cuttersnap.benchmark", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cases", type=Path)
    ap.add_argument("--photos", type=Path, required=True, help="folder holding the case photos")
    a = ap.parse_args(argv)
    rows = run(a.cases, a.photos)
    for r in rows:
        print(f"{r['name']:<28} {r['score'] if r['score'] is not None else r['note']}")
    scored = [r["score"] for r in rows if r["score"] is not None]
    if scored:
        print(f"{'mean':<28} {sum(scored) / len(scored):.3f}")


if __name__ == "__main__":
    main()
