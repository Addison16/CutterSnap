"""Build a sturdy, watertight cookie cutter solid from an outline.

The blade is built from horizontal slices, each one a Shapely buffer of the
outline. Buffers never fold over themselves, so tight inward notches cannot
produce a self-intersecting blade the way pushing vertices along their
normals can. The slices are fused with manifold3d, which always returns a
watertight solid.

Cross-section, bottom to top (all offsets measured outward from the cookie
outline, which is the blade's inner, cutting face):

    flange    0 .. flange_h                   out to wall_base + flange_w
    chamfer   flange_h .. +fillet             wall_base + fillet -> wall_base
    straight  .. straight_top                 wall_base
    taper     straight_top .. height          wall_base -> wall_tip
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

import cv2
import manifold3d as m3d
import numpy as np
import trimesh
from shapely.affinity import rotate, scale, translate
from shapely.geometry import MultiPolygon, Polygon
from shapely.ops import orient, polylabel, unary_union

from .outline import OutlineError, _exact, facet_error

CHAMFER_SLICES = 6
TAPER_SLICES = 16
QUAD_SEGS = 16    # arc segments per quarter circle where the blade rounds a point
TEXT_MAX = 3      # initials
TEXT_DEPTH = 0.6   # base text is pressed this deep into the underside
TEXT_STROKE = 0.6  # letter stroke width, about one and a half 0.4 mm lines


@dataclass
class CutterParams:
    """All dimensions in millimetres."""

    height: float = 18.0        # blade top above the bed
    flange_h: float = 2.4       # base thickness, printed flat on the bed
    flange_w: float = 6.0       # base width outside the blade
    wall_base: float = 1.6      # straight wall thickness (4 x 0.4 mm nozzle)
    wall_tip: float = 0.8       # cutting edge thickness (2 x 0.4 mm nozzle)
    fillet: float = 1.6         # chamfer from base into blade
    straight_top: float = 10.0  # where the straight wall starts to taper
    spread: float = 0.0         # shrink outline to undo dough spreading in the oven
    halo: float = 0.0           # grow outline for a "bubble" border around the design
    text: str = ""              # name or initials pressed into the underside of the base

    @classmethod
    def for_nozzle(cls, nozzle_mm: float, **overrides) -> "CutterParams":
        """Blade sized so the slicer lays down whole perimeters."""
        p = cls(wall_base=round(4 * nozzle_mm, 2), wall_tip=round(2 * nozzle_mm, 2))
        for k, v in overrides.items():
            setattr(p, k, v)
        if "straight_top" not in overrides:
            # keep the straight wall for a little under half the blade
            p.straight_top = round(p.flange_h + p.fillet + 0.43 * (p.height - p.flange_h - p.fillet), 2)
        p.validate()
        return p

    def warnings(self, nozzle_mm: float | None = None) -> list[str]:
        out = []
        if nozzle_mm and self.wall_tip < 2 * nozzle_mm - 1e-6:
            out.append(f"A {self.wall_tip} mm cutting edge is under two {nozzle_mm} mm lines; "
                       "turn on Arachne / thin-wall printing in your slicer.")
        return out

    def validate(self) -> None:
        if not 0.3 <= self.wall_tip <= self.wall_base:
            raise ValueError("cutting edge must be at least 0.3 mm and no thicker than the wall")
        if not self.flange_h + self.fillet <= self.straight_top < self.height:
            raise ValueError("taper must start above the chamfer and below the top")
        if min(self.height, self.flange_h, self.flange_w, self.fillet) <= 0 or min(self.spread, self.halo) < 0:
            raise ValueError("dimensions must be positive")
        if len(self.text) > TEXT_MAX or not all(" " <= ch <= "~" for ch in self.text):
            raise ValueError(f"initials must be up to {TEXT_MAX} plain letters or digits")

    def as_dict(self) -> dict:
        return asdict(self)


def _cross_section(geom) -> m3d.CrossSection:
    polys = geom.geoms if isinstance(geom, MultiPolygon) else [geom]
    rings = []
    for p in polys:
        p = orient(p, 1.0)
        rings.append(np.array(p.exterior.coords)[:-1])
        rings += [np.array(r.coords)[:-1] for r in p.interiors]
    return m3d.CrossSection(rings, m3d.FillRule.EvenOdd)


def _ring(inner: Polygon, offset: float):
    return inner.buffer(offset, join_style=1, quad_segs=QUAD_SEGS).difference(inner)


def _slab(inner: Polygon, offset: float, z0: float, z1: float) -> m3d.Manifold:
    return m3d.Manifold.extrude(_cross_section(_ring(inner, offset)), z1 - z0).translate((0, 0, z0))


def blade_profile(p: CutterParams) -> list[tuple[float, float, float]]:
    """(z0, z1, outward offset) for every slice above the flange."""
    out = []
    z = p.flange_h
    dz = p.fillet / CHAMFER_SLICES
    for i in range(CHAMFER_SLICES):
        # each slice takes the offset at its top, so the steps only ever step
        # inward going up: no overhangs anywhere on the outside of the blade
        out.append((z + i * dz, z + (i + 1) * dz,
                    p.wall_base + p.fillet * (1 - (i + 1) / CHAMFER_SLICES)))
    z += p.fillet
    if p.straight_top > z:
        out.append((z, p.straight_top, p.wall_base))
    z = p.straight_top
    dz = (p.height - z) / TAPER_SLICES
    for i in range(TAPER_SLICES):
        t = (i + 1) / TAPER_SLICES
        out.append((z + i * dz, z + (i + 1) * dz, p.wall_base + (p.wall_tip - p.wall_base) * t))
    return out


def mirrored(poly: Polygon) -> Polygon:
    """Left-right mirror image, in place."""
    x0, _, x1, _ = poly.bounds
    return orient(scale(poly, -1, 1, origin=((x0 + x1) / 2, 0)), 1.0)


def flipped(geom, about: Polygon | None = None):
    """Left-right mirror about the centre of `about` (default: geom itself),
    for the other one of a pair, like left and right mittens."""
    x0, _, x1, _ = (geom if about is None else about).bounds
    out = scale(geom, -1, 1, origin=((x0 + x1) / 2, 0))
    return orient(out, 1.0) if isinstance(out, Polygon) else out


def cutting_face(outline: Polygon, spread: float = 0.0, halo: float = 0.0,
                 min_convex_r: float = 1.5, min_concave_r: float = 2.5) -> Polygon:
    """The blade's inner face: the outline grown by the halo and shrunk by the
    dough spread.

    Shrinking makes outward points sharper by the same amount (and growing
    does it to notches), so the result is rounded to the minimum radii again.
    """
    poly = orient(outline, 1.0)
    d = halo - spread
    if not d:
        return poly
    moved = poly.buffer(d, join_style=1)
    try:
        if moved.is_empty or moved.geom_type != "Polygon":
            raise OutlineError
        return _exact(moved, min_convex_r, min_concave_r, 0.5)
    except OutlineError:
        raise ValueError("dough spread is too large for this cookie") from None


def _glyphs(text: str, height: float) -> list[tuple[MultiPolygon, float, float]]:
    """Each character as filled shapes in mm, centred on (0, 0), with its
    position and advance along the line. Capital height is `height`.

    Uses OpenCV's built-in Hershey stroke font, so no font files are needed.
    """
    ppm = 20.0
    font = cv2.FONT_HERSHEY_SIMPLEX
    (_, cap), _ = cv2.getTextSize("H", font, 1.0, 1)
    fs = height * ppm / cap
    th = max(1, round(TEXT_STROKE * ppm))
    out, x = [], 0.0
    for ch in text:
        (w, h), base = cv2.getTextSize(ch, font, fs, th)
        adv = w / ppm
        if ch != " ":
            pad = th + 4
            img = np.zeros((h + base + 2 * pad, w + 2 * pad), np.uint8)
            cv2.putText(img, ch, (pad, pad + h), font, fs, 255, th, cv2.LINE_AA)
            cnts, hier = cv2.findContours((img > 127).astype(np.uint8), cv2.RETR_CCOMP,
                                          cv2.CHAIN_APPROX_SIMPLE)
            polys = []
            for i, c in enumerate(cnts):
                if hier[0][i][3] != -1 or len(c) < 3:
                    continue
                holes, j = [], hier[0][i][2]
                while j != -1:
                    if len(cnts[j]) >= 3:
                        holes.append(cnts[j][:, 0, :])
                    j = hier[0][j][0]
                polys.append(Polygon(c[:, 0, :], holes).buffer(0))
            # pixels (y down) -> mm (y up), centred on the capital letters' middle
            g = scale(unary_union(polys), 1 / ppm, -1 / ppm, origin=(0, 0))
            g = translate(g, -(pad + w / 2) / ppm, (pad + (base + h) / 2) / ppm).simplify(0.02)
            out.append((g, x + adv / 2, adv))
        x += adv + 0.15 * height  # a little letter spacing
    return out


def place_text(face: Polygon, p: CutterParams):
    """Base text set along the base, following its curve, centred as low on
    the cookie as it fits, in the outline's own (unmirrored) frame. Letters
    stand with their tops toward the cookie. None when it does not fit."""
    text = p.text.strip()
    if not text:
        return None
    inner_off = p.wall_base + p.fillet + 0.5   # clear of the chamfer
    outer_off = p.wall_base + p.flange_w - 0.6  # and of the base's edge
    height = min(4.0, outer_off - inner_off - 1.0)
    if height < 2.0:
        return None
    glyphs = _glyphs(text, height)
    length = glyphs[-1][1] + glyphs[-1][2] / 2
    band = face.buffer(outer_off, join_style=1).difference(face.buffer(inner_off, join_style=1))
    path = orient(face.buffer((inner_off + outer_off) / 2, join_style=1), 1.0).exterior
    if length > 0.8 * path.length:
        return None
    # try centres from the bottom of the cookie upward
    starts = np.arange(0, path.length, 2.0)
    for c in sorted(starts, key=lambda d: path.interpolate(d).y):
        parts = []
        for g, x, _ in glyphs:
            d = (c - length / 2 + x) % path.length
            a, b = path.interpolate((d - 0.5) % path.length), path.interpolate((d + 0.5) % path.length)
            ang = np.degrees(np.arctan2(b.y - a.y, b.x - a.x))
            pt = path.interpolate(d)
            parts.append(translate(rotate(g, ang, origin=(0, 0)), pt.x, pt.y))
        placed = unary_union(parts)
        if band.contains(placed):
            return placed
    return None


def facet_error_mm(outline: Polygon, p: CutterParams) -> float:
    """Largest gap between the STL's flat facets and the smooth curve they
    follow, over the cutting face and the outside of the blade (the base's
    outer edge is left out: it has real corners where notches meet)."""
    face = cutting_face(outline, p.spread, p.halo)
    offs = {off for _, _, off in blade_profile(p)}
    return max([facet_error(face)] + [facet_error(face.buffer(o, join_style=1, quad_segs=QUAD_SEGS)) for o in offs])


def build_cutter(outline: Polygon, params: CutterParams | None = None,
                 notes: list[str] | None = None) -> trimesh.Trimesh:
    """Cutter mesh, printed base-down with the blade up.

    In use it is turned over, blade down, so it is built as the mirror image
    of the outline and the cookie comes out the same way round as the photo.
    Base text is pressed into the underside, which faces up in use. Anything
    the user should know (text that did not fit) is appended to `notes`.
    """
    p = params or CutterParams()
    p.validate()
    face = cutting_face(outline, p.spread, p.halo)
    inner = mirrored(face)
    parts = [_slab(inner, p.wall_base + p.flange_w, 0.0, p.flange_h)]
    parts += [_slab(inner, off, z0, z1) for z0, z1, off in blade_profile(p)]
    solid = m3d.Manifold.batch_boolean(parts, m3d.OpType.Add)
    if p.text.strip():
        label = place_text(face, p)
        if label is None:
            if notes is not None:
                notes.append("The initials did not fit on the base; try fewer letters or a wider base.")
        else:
            x0, _, x1, _ = face.bounds
            label = scale(label, -1, 1, origin=((x0 + x1) / 2, 0))  # same mirror as the face
            cut = m3d.Manifold.extrude(_cross_section(_multi(label)), TEXT_DEPTH + 0.01).translate((0, 0, -0.01))
            solid = solid - cut
    solid = solid.to_mesh()
    return trimesh.Trimesh(solid.vert_properties[:, :3], solid.tri_verts)


def _multi(geom) -> MultiPolygon:
    if isinstance(geom, Polygon):
        return MultiPolygon([geom])
    return MultiPolygon([g for g in geom.geoms if isinstance(g, Polygon)])


@dataclass
class PusherParams:
    """A plate that pushes dough out of the cutter, with a knob to hold."""

    clearance: float = 2.0   # gap between plate and blade, all round
    plate_h: float = 3.0     # plate thickness
    knob_d: float = 14.0     # largest knob diameter; smaller shapes get a thinner knob
    knob_above: float = 5.0  # knob sticks out this far when the plate is at the blade tip


def build_pusher(outline: Polygon, params: CutterParams | None = None,
                 pusher: PusherParams | None = None) -> tuple[trimesh.Trimesh, list[str]]:
    """Pusher plate for the cutter `build_cutter(outline, params)` makes.

    Returns the mesh and any notes for the user (for example, when the shape
    is so narrow that only its largest part gets a plate).
    """
    p = params or CutterParams()
    q = pusher or PusherParams()
    notes = []
    inner = cutting_face(outline, p.spread, p.halo)
    # shrink, then drop slivers narrower than 2 mm that would snap off
    plate = inner.buffer(-q.clearance, join_style=1).buffer(-1.0).buffer(1.0, join_style=1)
    if plate.is_empty:
        raise ValueError("this cookie is too narrow for a pusher plate")
    if isinstance(plate, MultiPolygon):
        plate = max(plate.geoms, key=lambda g: g.area)
        notes.append("The pusher covers only the largest part of the shape; narrow parts are left out.")
    centre = polylabel(plate, tolerance=0.05)
    room = plate.exterior.distance(centre)
    r = min(q.knob_d / 2, room - 1.0)
    if r < 2.5:
        raise ValueError("this cookie is too narrow for a pusher knob")
    flare_r = min(r + 2.0, room - 0.5)  # the flare stays on the plate
    knob_h = p.height - q.plate_h + q.knob_above
    base = m3d.Manifold.extrude(_cross_section(plate), q.plate_h)
    # knob flares into the plate so it doesn't snap at the joint
    flare = m3d.Manifold.cylinder(2.0, flare_r, r, 48).translate((centre.x, centre.y, q.plate_h))
    knob = m3d.Manifold.cylinder(knob_h, r, r, 48).translate((centre.x, centre.y, q.plate_h))
    solid = m3d.Manifold.batch_boolean([base, flare, knob], m3d.OpType.Add).to_mesh()
    return trimesh.Trimesh(solid.vert_properties[:, :3], solid.tri_verts), notes
