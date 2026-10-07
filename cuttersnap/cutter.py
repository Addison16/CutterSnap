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

import manifold3d as m3d
import numpy as np
import trimesh
from shapely.geometry import MultiPolygon, Polygon
from shapely.ops import orient

CHAMFER_SLICES = 6
TAPER_SLICES = 16


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
        if min(self.height, self.flange_h, self.flange_w, self.fillet) <= 0 or self.spread < 0:
            raise ValueError("dimensions must be positive")

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
    return inner.buffer(offset, join_style=1, quad_segs=8).difference(inner)


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


def build_cutter(outline: Polygon, params: CutterParams | None = None) -> trimesh.Trimesh:
    p = params or CutterParams()
    p.validate()
    inner = orient(outline, 1.0)
    if p.spread:
        inner = inner.buffer(-p.spread, join_style=1)
        if inner.is_empty or inner.geom_type != "Polygon":
            raise ValueError("dough spread is too large for this cookie")
    parts = [_slab(inner, p.wall_base + p.flange_w, 0.0, p.flange_h)]
    parts += [_slab(inner, off, z0, z1) for z0, z1, off in blade_profile(p)]
    solid = m3d.Manifold.batch_boolean(parts, m3d.OpType.Add).to_mesh()
    return trimesh.Trimesh(solid.vert_properties[:, :3], solid.tri_verts)
