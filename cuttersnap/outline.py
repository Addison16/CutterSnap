"""Turn a cookie mask into a smooth, printable outline in millimetres."""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np
from scipy.interpolate import splev, splprep
from shapely.geometry import Polygon
from shapely.ops import orient


@dataclass
class Outline:
    polygon: Polygon          # CCW, millimetres, origin at bottom-left of bounds
    px_per_mm: float          # photo pixels per millimetre
    origin_px: tuple[float, float]  # photo pixel (x, y) of the mm origin

    def to_pixels(self) -> np.ndarray:
        """Outline points mapped back onto the photo, for drawing an overlay."""
        p = np.array(self.polygon.exterior.coords)
        ox, oy = self.origin_px
        return np.c_[ox + p[:, 0] * self.px_per_mm, oy - p[:, 1] * self.px_per_mm]


class OutlineError(ValueError):
    pass


def _largest(geom):
    if geom.is_empty:
        raise OutlineError("the shape vanished; it is smaller than the minimum feature size")
    if geom.geom_type == "Polygon":
        return geom
    return max(geom.geoms, key=lambda g: g.area)


def mask_to_outline(
    mask: np.ndarray,
    size_mm: float,
    min_convex_r: float = 1.5,
    min_concave_r: float = 2.5,
    spacing_mm: float = 0.5,
) -> Outline:
    """Trace the mask and enforce the smoothness rules.

    size_mm sets the longest side of the finished cookie. min_convex_r rounds
    outward points, min_concave_r fills inward notches, and the result is a
    closed smoothing spline resampled every spacing_mm.
    """
    if not mask.any():
        raise OutlineError("no cookie found in the selection")
    # anti-aliased edge: blur, then contour at 50% so there are no pixel stairs
    k = max(3, int(min(mask.shape) * 0.006) | 1)
    soft = cv2.GaussianBlur(mask, (k, k), 0)
    cnts, _ = cv2.findContours((soft > 127).astype(np.uint8), cv2.RETR_EXTERNAL,
                               cv2.CHAIN_APPROX_NONE)
    c = max(cnts, key=cv2.contourArea)[:, 0, :].astype(float)
    if len(c) < 8:
        raise OutlineError("selection is too small to trace")
    c[:, 1] *= -1  # image y-down -> CAD y-up
    poly = _largest(Polygon(c).buffer(0))
    minx, miny, maxx, maxy = poly.bounds
    px_per_mm = max(maxx - minx, maxy - miny) / size_mm
    raw = (np.array(poly.exterior.coords) - [minx, miny]) / px_per_mm

    # rounding corners shrinks the shape, so run the rules a second time at the
    # corrected scale; the final uniform rescale is then within a percent or two
    smooth = _rules(Polygon(raw), min_convex_r, min_concave_r, spacing_mm)
    bx0, by0, bx1, by1 = smooth.bounds
    scale = size_mm / max(bx1 - bx0, by1 - by0)
    smooth = _rules(Polygon(raw * scale), min_convex_r, min_concave_r, spacing_mm)
    # the smoothing spline can re-sharpen a corner slightly: measure after
    # smoothing and re-apply the rules until every point passes
    for _ in range(3):
        if check_outline(smooth, min_convex_r, min_concave_r, tolerance=1.0)["ok"]:
            break
        smooth = _rules(smooth, min_convex_r, min_concave_r, spacing_mm)
    else:
        # the spline keeps re-tightening some corner: finish with exact
        # buffer arcs, resampled without a spline, which cannot overshoot
        smooth = _exact(smooth, min_convex_r, min_concave_r, spacing_mm)
    bx0, by0, bx1, by1 = smooth.bounds
    k = size_mm / max(bx1 - bx0, by1 - by0)
    pts = (np.array(smooth.exterior.coords) - [bx0, by0]) * k
    return Outline(orient(Polygon(pts), 1.0), *_pixel_frame(minx, miny, px_per_mm, scale, k, bx0, by0))


def _pixel_frame(minx, miny, px_per_mm, scale, k, bx0, by0):
    """px_per_mm and pixel origin for the final mm frame.

    final_mm = (raw_mm * scale - b0) * k, and raw_mm = (pixel - min) / px_per_mm
    so pixel = min + (final_mm / k + b0) / scale * px_per_mm.
    """
    ppm = px_per_mm / (scale * k)
    ox = minx + bx0 / scale * px_per_mm
    oy = miny + by0 / scale * px_per_mm  # in the y-flipped frame
    return ppm, (ox, -oy)


RADIUS_MARGIN = 1.2  # the spline pulls corners in a little; aim above the minimum


def _rules(poly: Polygon, min_convex_r: float, min_concave_r: float, spacing_mm: float) -> Polygon:
    # morphological opening then closing in real units = minimum corner radii
    min_convex_r, min_concave_r = min_convex_r * RADIUS_MARGIN, min_concave_r * RADIUS_MARGIN
    poly = _largest(poly.buffer(-min_convex_r, join_style=1).buffer(min_convex_r, join_style=1))
    poly = _largest(poly.buffer(min_concave_r, join_style=1).buffer(-min_concave_r, join_style=1))
    poly = orient(poly.simplify(0.05), 1.0)
    # periodic smoothing spline -> evenly spaced points, no kinks
    p = np.array(poly.exterior.coords)[:-1]
    tck, _ = splprep([p[:, 0], p[:, 1]], s=len(p) * 0.004, per=True)
    n = max(64, int(poly.length / spacing_mm))
    x, y = splev(np.linspace(0, 1, n, endpoint=False), tck)
    return orient(_largest(Polygon(np.c_[x, y]).buffer(0)), 1.0)


def _exact(poly: Polygon, min_convex_r: float, min_concave_r: float, spacing_mm: float) -> Polygon:
    """Opening and closing with true arcs, then even resampling along the edge."""
    m = 1.05  # covers the final rescale to size, which is within a few percent
    q = {"join_style": 1, "quad_segs": 32}
    poly = _largest(poly.buffer(-min_convex_r * m, **q).buffer(min_convex_r * m, **q))
    poly = _largest(poly.buffer(min_concave_r * m, **q).buffer(-min_concave_r * m, **q))
    ring = orient(poly, 1.0).exterior
    n = max(64, int(ring.length / spacing_mm))
    pts = [ring.interpolate(d) for d in np.linspace(0, ring.length, n, endpoint=False)]
    return orient(Polygon([(p.x, p.y) for p in pts]), 1.0)


def check_outline(poly: Polygon, min_convex_r: float = 1.5, min_concave_r: float = 2.5,
                  tolerance: float = 0.9) -> dict:
    """Radius of curvature at every point of the final outline.

    Radius comes from the circle through each point and its neighbours; the
    sign of the turn tells outward points (convex) from notches (concave).
    Passing means no point is sharper than tolerance x the minimum radius.
    """
    p = np.array(orient(poly, 1.0).exterior.coords)[:-1]
    a, b = p - np.roll(p, 1, 0), np.roll(p, -1, 0) - p
    c = np.roll(p, -1, 0) - np.roll(p, 1, 0)
    cross = a[:, 0] * b[:, 1] - a[:, 1] * b[:, 0]
    la, lb, lc = (np.linalg.norm(v, axis=1) for v in (a, b, c))
    with np.errstate(divide="ignore"):
        r = la * lb * lc / np.abs(2 * cross)
    convex = r[cross > 0].min(initial=np.inf)
    concave = r[cross < 0].min(initial=np.inf)
    return {
        "min_convex_radius_mm": round(float(convex), 2),
        "min_concave_radius_mm": round(float(concave), 2),
        "max_turn_deg": round(max_turn_deg(poly), 1),
        "ok": bool(convex >= tolerance * min_convex_r and concave >= tolerance * min_concave_r),
    }


def max_turn_deg(poly: Polygon) -> float:
    """Largest direction change between consecutive outline segments."""
    p = np.array(poly.exterior.coords)[:-1]
    d = np.roll(p, -1, 0) - p
    a = np.arctan2(d[:, 1], d[:, 0])
    t = np.degrees(np.abs((np.roll(a, -1) - a + np.pi) % (2 * np.pi) - np.pi))
    return float(t.max())
