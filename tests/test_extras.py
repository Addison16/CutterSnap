"""Initials on the base, halo, mirror pairs, facet check and rounded corners."""
import numpy as np
import pytest
from shapely.geometry import Point, Polygon

from cuttersnap.cutter import (
    CutterParams,
    build_cutter,
    cutting_face,
    facet_error_mm,
    flipped,
    place_text,
)
from cuttersnap.outline import check_outline, facet_error, mask_to_outline


def circle(r=40):
    return Polygon(Point(45, 45).buffer(r, 256).exterior.coords)


def test_initials_pressed_into_the_underside():
    plain = build_cutter(circle())
    notes = []
    named = build_cutter(circle(), CutterParams(text="ABC"), notes)
    assert named.is_watertight and not notes
    assert 1 < plain.volume - named.volume < 60
    # only the bottom 0.6 mm is touched, below the cookie (the letters are low on it)
    new = named.vertices[~np.isin(named.vertices.round(4).view("f8,f8,f8"),
                                   plain.vertices.round(4).view("f8,f8,f8")).ravel()]
    assert new[:, 2].max() <= 0.6 + 1e-6
    assert new[:, 1].max() < 10


def test_initials_that_do_not_fit_are_reported():
    notes = []
    build_cutter(circle(), CutterParams(text="ABC", flange_w=3.0), notes)
    assert notes and "did not fit" in notes[0]


def test_initials_are_limited_to_three_plain_characters():
    for bad in ("ABCD", "é"):
        with pytest.raises(ValueError):
            CutterParams(text=bad).validate()


def test_initials_read_correctly_from_underneath():
    # placed in the photo frame reading left to right along the bottom
    label = place_text(circle(), CutterParams(text="L"))
    assert label is not None
    x0, y0, x1, y1 = label.bounds
    # an L's foot runs to the right of its upright stem
    stem = label.intersection(Polygon([(x0, y0), (x0 + 0.8, y0), (x0 + 0.8, y1), (x0, y1)]))
    assert stem.area > 0.5


def test_halo_grows_the_cookie_and_keeps_radii():
    face = cutting_face(circle(), halo=5)
    x0, _, x1, _ = face.bounds
    assert x1 - x0 == pytest.approx(90, abs=0.2)
    star = Polygon([(np.cos(a) * r + 50, np.sin(a) * r + 50)
                    for a, r in zip(np.linspace(0, 2 * np.pi, 10, endpoint=False), [40, 18] * 5)])
    o = mask_to_outline(_mask(star), 90).polygon
    assert check_outline(cutting_face(o, halo=6))["ok"]


def test_flip_makes_the_mirror_image():
    p = Polygon([(0, 0), (40, 0), (40, 10), (10, 30), (0, 30)])
    f = flipped(p)
    assert f.bounds == pytest.approx(p.bounds)
    assert f.contains(Point(38, 28)) and not p.contains(Point(38, 28))


def test_facets_hug_the_curve():
    assert facet_error(circle()) < 0.01
    o = mask_to_outline(_mask(Polygon([(10, 10), (90, 10), (50, 80)])), 80).polygon
    assert facet_error_mm(o, CutterParams()) < 0.05


def test_rounded_corners_are_pointed_out():
    tri = mask_to_outline(_mask(Polygon([(10, 10), (90, 10), (50, 80)])), 80)
    assert len(tri.rounded_mm) == 3  # one per corner
    box = mask_to_outline(_mask(Point(50, 50).buffer(40)), 80)
    assert box.rounded_mm == []


def _mask(poly, k=8):
    import cv2

    m = np.zeros((100 * k, 100 * k), np.uint8)
    cv2.fillPoly(m, [np.int32(np.array(poly.exterior.coords) * k)], 255)
    return m


def test_straight_sides_stay_straight():
    # a spline through a simplified straight side used to bulge out by 10 mm
    tri = Polygon([(10, 10), (90, 10), (50, 80)])
    o = mask_to_outline(_mask(tri), 80)
    px = o.to_pixels()[:-1]
    truth = Polygon(np.array(tri.exterior.coords) * 8)
    away = [p for p in px if min(np.hypot(*(p - np.array(c) * 8)) for c in tri.exterior.coords) > 12 * 8]
    assert away and max(truth.exterior.distance(Point(p)) for p in away) / o.px_per_mm < 0.3
