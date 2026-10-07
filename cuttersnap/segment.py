"""Find the cookie in a photo with classical computer vision. No ML models.

Two stages, both plain OpenCV:

1. Edge prior. Canny edges inside the user's box are thickened just enough to
   close small gaps, and everything the box border cannot flood into is taken
   as "enclosed". This finds the cookie's outer edge even when the icing is
   the same colour as the background, and it ignores icing detail inside.
2. GrabCut refines a narrow band around that shape using colour, and obeys
   the user's "cookie" / "not cookie" clicks.
"""
from __future__ import annotations

from typing import Sequence

import cv2
import numpy as np

Point = tuple[int, int]
Rect = tuple[int, int, int, int]

WORK_PX = 350          # the box's longest side is resampled to this many pixels
GAPS = (3, 5, 7, 9, 11, 13, 15)
PLATEAU = 1.04         # region growth under which a gap size counts as "settled"


def _ellipse(d: int) -> np.ndarray:
    return cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (d, d))


def _enclosed(edges: np.ndarray, gap: int) -> np.ndarray:
    """Pixels the box border cannot reach once edges are thickened by `gap`."""
    k = _ellipse(gap)
    free = (cv2.dilate(edges, k) == 0).astype(np.uint8)
    _, lab = cv2.connectedComponents(free, connectivity=4)
    border = set(np.unique(np.r_[lab[0], lab[-1], lab[:, 0], lab[:, -1]])) - {0}
    inside = (~np.isin(lab, list(border))).astype(np.uint8) * 255
    # opening cuts thin contacts with neighbouring cookies
    return cv2.morphologyEx(inside, cv2.MORPH_OPEN, k)


def edge_prior(roi: np.ndarray, fg: Sequence[Point], bg: Sequence[Point]) -> np.ndarray | None:
    """Shape enclosed by the cookie's outer edge, or None if no clean edge."""
    gray = cv2.bilateralFilter(cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY), 7, 40, 7)
    edges = cv2.Canny(gray, 20, 60)
    h, w = gray.shape
    cands = []
    for gap in GAPS:
        _, lab = cv2.connectedComponents(_enclosed(edges, gap))
        ids = {int(lab[y, x]) for x, y in fg}
        if len(ids) != 1 or 0 in ids:
            continue
        comp = lab == ids.pop()
        if any(comp[y, x] for x, y in bg):
            continue
        if not 0.15 * h * w <= comp.sum() <= 0.95 * h * w:
            continue
        cands.append(comp)
    # smallest gap after which the region stops growing: edges are closed
    # enough to hold the outline but not yet bridging into the background
    for a, b in zip(cands, cands[1:]):
        if b.sum() <= PLATEAU * a.sum():
            return a.astype(np.uint8) * 255
    return cands[-1].astype(np.uint8) * 255 if cands else None


def _fill(mask: np.ndarray) -> np.ndarray:
    """Fill holes: icing details inside the cookie are not the outline."""
    cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    filled = np.zeros_like(mask)
    cv2.drawContours(filled, cnts, -1, 255, -1)
    return filled


def _grabcut(im, box, prior, clicks, iters) -> np.ndarray:
    """One GrabCut run; with a prior, only a band around its rim is uncertain."""
    h, w = im.shape[:2]
    x, y, rw, rh = box
    mask = np.full((h, w), cv2.GC_BGD, np.uint8)
    roi = mask[y:y + rh, x:x + rw]
    if prior is None:
        roi[:] = cv2.GC_PR_FGD
    else:
        band = _ellipse(2 * max(3, int(0.04 * max(rw, rh))) + 1)
        roi[:] = cv2.GC_PR_BGD
        roi[prior > 0] = cv2.GC_PR_FGD
        roi[cv2.erode(prior, band) > 0] = cv2.GC_FGD
        roi[cv2.dilate(prior, band) == 0] = cv2.GC_BGD
    rad = max(2, int(0.02 * max(rw, rh)))
    for pts, val in zip(clicks, (cv2.GC_FGD, cv2.GC_BGD)):
        for p in pts or ():
            cv2.circle(mask, p, rad, int(val), -1)
    bgd, fgd = np.zeros((1, 65), np.float64), np.zeros((1, 65), np.float64)
    cv2.grabCut(im, mask, None, bgd, fgd, iters, cv2.GC_INIT_WITH_MASK)
    return np.where((mask == cv2.GC_FGD) | (mask == cv2.GC_PR_FGD), 255, 0).astype(np.uint8)


def segment(
    img: np.ndarray,
    rect: Rect | None = None,
    fg: Sequence[Point] = (),
    bg: Sequence[Point] = (),
    iters: int = 6,
) -> np.ndarray:
    """Return a filled 0/255 cookie mask at the photo's full resolution.

    rect is the user's box (x, y, w, h); fg and bg are "cookie" and
    "not cookie" clicks. All are in the photo's own pixel coordinates.
    """
    full_h, full_w = img.shape[:2]
    if rect is None:
        m = int(0.03 * min(full_h, full_w))
        rect = (m, m, full_w - 2 * m, full_h - 2 * m)
    bx, by, bw, bh = rect
    # work on the box plus a margin, resampled to a fixed size so thresholds
    # behave the same for a tiny cookie in a screenshot and a close-up photo
    pad = int(0.15 * max(bw, bh))
    x0, y0 = max(0, bx - pad), max(0, by - pad)
    x1, y1 = min(full_w, bx + bw + pad), min(full_h, by + bh + pad)
    f = min(1.0, WORK_PX / max(bw, bh))
    im = cv2.resize(img[y0:y1, x0:x1], None, fx=f, fy=f, interpolation=cv2.INTER_AREA)
    h, w = im.shape[:2]

    def to_work(p: Point) -> Point:
        return min(w - 1, max(0, int((p[0] - x0) * f))), min(h - 1, max(0, int((p[1] - y0) * f)))

    x, y = to_work((bx, by))
    rw, rh = max(2, min(int(bw * f), w - x)), max(2, min(int(bh * f), h - y))
    fgs = [to_work(p) for p in fg] or [(x + rw // 2, y + rh // 2)]
    bgs = [to_work(p) for p in bg]

    prior = edge_prior(im[y:y + rh, x:x + rw],
                       [(a - x, b - y) for a, b in fgs],
                       [(a - x, b - y) for a, b in bgs if x <= a < x + rw and y <= b < y + rh])
    clicks = (fg and fgs, bgs)
    out = _grabcut(im, (x, y, rw, rh), prior, clicks, iters)

    # keep the blob(s) under the cookie clicks, else the largest
    n, lab, stats, _ = cv2.connectedComponentsWithStats(out)
    if n > 1:
        keep = {int(lab[b, a]) for a, b in fgs} - {0}
        keep = keep or {1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))}
        out = np.isin(lab, list(keep)).astype(np.uint8) * 255
    filled = _fill(out)

    result = np.zeros((full_h, full_w), np.uint8)
    result[y0:y1, x0:x1] = cv2.resize(filled, (x1 - x0, y1 - y0), interpolation=cv2.INTER_LINEAR)
    return result
