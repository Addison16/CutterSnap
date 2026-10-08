"""Matching stamp: a plate that fits inside the cutter with the cookie's
icing lines raised on its face, to press the design into the dough.

The cutter follows the dough and ignores icing; the stamp does the opposite
and keeps only the lines inside the cookie. Lines are colour edges (Canny on
each Lab channel of a median- and bilateral-filtered copy, so gloss and
crumbs mostly drop out), thickened to a printable width and cleaned of
specks. `level` (0 to 1) trades a cleaner stamp for fainter detail.
"""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import manifold3d as m3d
import numpy as np
import trimesh
from shapely.affinity import scale
from shapely.geometry import MultiPolygon, Polygon
from shapely.ops import orient, unary_union

from .cutter import CutterParams, _cross_section, mirrored
from .outline import Outline

WORK_PX_PER_MM = 6.0   # photo resampled to this resolution before finding lines
MARGIN_MM = 2.5        # no lines this close to the cookie's edge
SPECK_MM = 2.5         # line pieces smaller than this square are dropped


@dataclass
class StampParams:
    clearance: float = 1.0   # gap between stamp and blade, all round
    plate_h: float = 4.0     # plate thickness; the back is flat to press on
    relief_h: float = 2.0    # how far the lines stand off the plate
    line_mm: float = 1.2     # line width, at least two 0.4 mm nozzle lines + a bit


def detail_lines(img: np.ndarray, outline: Outline, level: float = 0.5,
                 line_mm: float = 1.2) -> MultiPolygon:
    """Icing lines inside the outline, as shapes in the outline's mm frame."""
    level = float(np.clip(level, 0.0, 1.0))
    ppm, (ox, oy) = outline.px_per_mm, outline.origin_px
    px = outline.to_pixels()
    x0, y0 = np.floor(px.min(0)).astype(int) - 2
    x1, y1 = np.ceil(px.max(0)).astype(int) + 2
    h, w = img.shape[:2]
    x0, y0, x1, y1 = max(0, x0), max(0, y0), min(w, x1), min(h, y1)
    f = WORK_PX_PER_MM / ppm
    crop = cv2.resize(img[y0:y1, x0:x1], None, fx=f, fy=f,
                      interpolation=cv2.INTER_AREA if f < 1 else cv2.INTER_CUBIC)
    k = WORK_PX_PER_MM  # work pixels per mm

    inside = np.zeros(crop.shape[:2], np.uint8)
    cv2.fillPoly(inside, [np.round((px - [x0, y0]) * f).astype(np.int32)], 255)
    inside = cv2.erode(inside, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (int(2 * MARGIN_MM * k) | 1,) * 2))

    smooth = cv2.bilateralFilter(cv2.medianBlur(crop, 5), 9, 40, 9)
    lab = cv2.cvtColor(smooth, cv2.COLOR_BGR2LAB)
    lo = 70 - 50 * level  # Canny thresholds: lower finds fainter lines
    edges = np.zeros(inside.shape, np.uint8)
    for c in range(3):
        edges |= cv2.Canny(lab[..., c], lo, 3 * lo)
    edges &= inside
    lw = max(3, int(round(line_mm * k)) | 1)
    lines = cv2.dilate(edges, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (lw, lw)))
    n, lab_ids, stats, _ = cv2.connectedComponentsWithStats(lines)
    keep = [i for i in range(1, n) if stats[i, cv2.CC_STAT_AREA] >= (SPECK_MM * k) ** 2]
    lines = np.isin(lab_ids, keep).astype(np.uint8) * 255

    cnts, hier = cv2.findContours(lines, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
    polys = []
    if hier is not None:
        def to_mm(c):
            p = c[:, 0, :] / f + [x0, y0]
            return np.c_[(p[:, 0] - ox) / ppm, (oy - p[:, 1]) / ppm]
        for i, c in enumerate(cnts):
            if hier[0][i][3] != -1 or len(c) < 3:
                continue  # holes are attached to their outer contour below
            holes = []
            j = hier[0][i][2]
            while j != -1:
                if len(cnts[j]) >= 3:
                    holes.append(to_mm(cnts[j]))
                j = hier[0][j][0]
            polys.append(Polygon(to_mm(c), holes).buffer(0))
    shape = unary_union(polys) if polys else MultiPolygon()
    # round the pixel stairs off and drop slivers thinner than half a line
    shape = shape.buffer(-0.25 * line_mm, join_style=1).buffer(0.25 * line_mm, join_style=1).simplify(0.05)
    return _multi(shape)


def _multi(geom) -> MultiPolygon:
    if geom.is_empty:
        return MultiPolygon()
    if isinstance(geom, Polygon):
        return MultiPolygon([geom])
    return MultiPolygon([g for g in getattr(geom, "geoms", []) if isinstance(g, Polygon)])


def build_stamp(outline: Polygon, detail: MultiPolygon, params: CutterParams | None = None,
                stamp: StampParams | None = None) -> trimesh.Trimesh:
    """Stamp mesh, printed plate-down with the lines facing up.

    In use it is turned over onto the dough, so it is built mirrored, and the
    imprint comes out the same way round as the photo.
    """
    p = params or CutterParams()
    s = stamp or StampParams()
    inner = orient(outline, 1.0)
    if p.spread:
        inner = inner.buffer(-p.spread, join_style=1)
    plate = inner.buffer(-s.clearance, join_style=1)
    if plate.is_empty:
        raise ValueError("this cookie is too small for a stamp")
    if isinstance(plate, MultiPolygon):
        plate = max(plate.geoms, key=lambda g: g.area)
    relief = detail.intersection(plate.buffer(-1.0)) if not detail.is_empty else detail
    if relief.is_empty or relief.area < 1.0:
        raise ValueError("no icing lines were found inside the cookie for a stamp")
    cx = (plate.bounds[0] + plate.bounds[2]) / 2
    plate, relief = mirrored(plate), scale(relief, -1, 1, origin=(cx, 0))
    parts = [m3d.Manifold.extrude(_cross_section(orient(plate, 1.0)), s.plate_h),
             m3d.Manifold.extrude(_cross_section(_multi(relief)), s.relief_h + 0.01)
             .translate((0, 0, s.plate_h - 0.01))]
    solid = m3d.Manifold.batch_boolean(parts, m3d.OpType.Add).to_mesh()
    return trimesh.Trimesh(solid.vert_properties[:, :3], solid.tri_verts)


def rings(geom: MultiPolygon, to_px=None) -> list:
    """Shapes as JSON-friendly [[exterior points], [hole points], ...]."""
    out = []
    for g in geom.geoms:
        pts = [np.array(r.coords)[:-1] for r in (g.exterior, *g.interiors)]
        if to_px:
            pts = [to_px(p) for p in pts]
        out.append([np.round(p, 2).tolist() for p in pts])
    return out


def from_rings(data: list) -> MultiPolygon:
    """Inverse of rings(); tolerates hand-edited or partly erased data."""
    polys = []
    for shape in data:
        if shape and len(shape[0]) >= 3:
            polys.append(Polygon(shape[0], [h for h in shape[1:] if len(h) >= 3]).buffer(0))
    return _multi(unary_union(polys)) if polys else MultiPolygon()
