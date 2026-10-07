import cv2
import numpy as np
import pytest
from conftest import iou

from cuttersnap.livewire import edge_mask


def _anchors(truth, n, push=0):
    """n points spread around the truth's edge, optionally pushed outward."""
    if push:
        truth = cv2.dilate(truth, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * push + 1,) * 2))
    c = max(cv2.findContours(truth, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)[0], key=cv2.contourArea)[:, 0]
    return [tuple(int(v) for v in c[i]) for i in np.linspace(0, len(c) - 1, n, endpoint=False).astype(int)]


def test_edge_points_follow_rim_not_stripes(white_on_white):
    img, truth = white_on_white
    img = img.copy()
    # dark candy-cane stripes on the icing, close to the rim
    inner = cv2.erode(truth, np.ones((13, 13), np.uint8))
    stripes = np.zeros_like(truth)
    for k in range(-500, 500, 18):
        cv2.line(stripes, (k, 0), (k + 500, 500), 255, 2)
    img[(stripes > 0) & (inner > 0)] = (150, 140, 170)
    mask = edge_mask(img, _anchors(truth, 8, push=3))
    assert iou(mask, truth) > 0.95


def test_edge_points_on_star(star_photo):
    img, truth = star_photo
    # one point per tip and per notch, as a person would click
    mask = edge_mask(img, _anchors(truth, 10))
    assert iou(mask, truth) > 0.95


def test_needs_three_points(star_photo):
    with pytest.raises(ValueError):
        edge_mask(star_photo[0], [(10, 10), (50, 50)])
