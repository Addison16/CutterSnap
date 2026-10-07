"""Edge points: the user clicks a few points on the cookie's edge and the
outline follows the strongest edge between them (OpenCV Intelligent Scissors).

This is the tool for photos where automatic tracing locks onto icing, such
as white-on-white cookies or icing with strong stripes. A median filter wipes
out thin icing lines before the edge costs are computed, so the path prefers
the cookie's outer edge over stripes.
"""
from __future__ import annotations

from collections.abc import Sequence

import cv2
import numpy as np

Point = tuple[int, int]

WORK_PX = 700     # longest side of the anchors' area after resampling
PAD = 0.08        # margin around the anchors, as a fraction of their extent
SNAP = 0.008      # anchors move to the strongest edge within this fraction


def _snap(grad: np.ndarray, p: Point, r: int) -> Point:
    h, w = grad.shape
    x, y = p
    x0, y0 = max(0, x - r), max(0, y - r)
    win = grad[y0:min(h, y + r + 1), x0:min(w, x + r + 1)]
    if win.size == 0 or win.max() <= 0:
        return p
    dy, dx = np.unravel_index(int(np.argmax(win)), win.shape)
    return x0 + int(dx), y0 + int(dy)


def edge_path(img: np.ndarray, anchors: Sequence[Point], snap: bool = True) -> np.ndarray:
    """Closed path through the anchors along image edges, in photo pixels (N x 2)."""
    if len(anchors) < 3:
        raise ValueError("need at least 3 edge points")
    full_h, full_w = img.shape[:2]
    pts = np.asarray(anchors, np.float64)
    lo, hi = pts.min(0), pts.max(0)
    pad = PAD * max(hi - lo) + 4
    x0, y0 = (np.maximum(0, lo - pad)).astype(int)
    x1, y1 = (np.minimum([full_w, full_h], hi + pad + 1)).astype(int)
    f = min(1.0, WORK_PX / max(x1 - x0, y1 - y0))
    roi = cv2.resize(img[y0:y1, x0:x1], None, fx=f, fy=f, interpolation=cv2.INTER_AREA)
    h, w = roi.shape[:2]
    smooth = cv2.medianBlur(roi, max(3, (max(h, w) // 100) | 1))

    work = [(min(w - 1, max(0, int((x - x0) * f))), min(h - 1, max(0, int((y - y0) * f))))
            for x, y in anchors]
    if snap:
        gray = cv2.cvtColor(smooth, cv2.COLOR_BGR2GRAY).astype(np.float32)
        grad = cv2.magnitude(cv2.Sobel(gray, cv2.CV_32F, 1, 0), cv2.Sobel(gray, cv2.CV_32F, 0, 1))
        r = max(2, int(SNAP * max(h, w)))
        work = [_snap(grad, p, r) for p in work]

    tool = cv2.segmentation.IntelligentScissorsMB()
    tool.setEdgeFeatureCannyParameters(16, 48)
    tool.setGradientMagnitudeMaxLimit(200)
    tool.applyImage(smooth)
    parts = []
    for i, p in enumerate(work):
        tool.buildMap(p)
        seg = tool.getContour(work[(i + 1) % len(work)]).reshape(-1, 2)
        parts.append(seg[:-1])  # the next segment starts at the shared anchor
    path = np.concatenate(parts).astype(np.float64)
    return path / f + [x0, y0]


def edge_mask(img: np.ndarray, anchors: Sequence[Point], snap: bool = True) -> np.ndarray:
    """Filled 0/255 mask of the edge-point outline at the photo's resolution."""
    path = edge_path(img, anchors, snap)
    mask = np.zeros(img.shape[:2], np.uint8)
    cv2.fillPoly(mask, [np.round(path).astype(np.int32)], 255)
    # a path that doubles back can leave slivers or holes; keep the filled outer shape
    cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    out = np.zeros_like(mask)
    if cnts:
        cv2.drawContours(out, [max(cnts, key=cv2.contourArea)], -1, 255, -1)
    return out
