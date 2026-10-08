"""HTTP API and web UI."""
from __future__ import annotations

import io
import json
from pathlib import Path

import numpy as np
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from PIL import Image, ImageOps
from pydantic import BaseModel, Field
from shapely.affinity import scale
from shapely.geometry import Polygon
from shapely.ops import orient

from . import __version__
from .bundle import size_set
from .cutter import (CutterParams, PusherParams, build_cutter, build_pusher, cutting_face,
                     facet_error_mm)
from .livewire import edge_mask
from .outline import Outline, OutlineError, check_outline, mask_to_outline
from .segment import segment
from .stamp import StampParams, build_stamp, detail_lines, from_rings, rings

try:  # iPhone photos
    from pillow_heif import register_heif_opener

    register_heif_opener()
except ImportError:  # pragma: no cover
    pass

MAX_UPLOAD = 25 * 1024 * 1024
STATIC = Path(__file__).parent / "static"

app = FastAPI(title="CutterSnap", version=__version__)
app.mount("/static", StaticFiles(directory=STATIC), name="static")


MAX_PIXELS = 50_000_000  # a 48 MP phone photo fits; larger is rejected before decoding


async def _read_upload(upload: UploadFile) -> bytes:
    """Read at most MAX_UPLOAD bytes so a huge upload is refused, not buffered."""
    data = await upload.read(MAX_UPLOAD + 1)
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, "image is larger than 25 MB")
    return data


def _read_image(data: bytes) -> np.ndarray:
    try:
        im = Image.open(io.BytesIO(data))
        # header only so far: refuse decompression bombs before decoding pixels
        if im.width * im.height > MAX_PIXELS:
            raise HTTPException(413, "image has more than 50 megapixels")
        im = ImageOps.exif_transpose(im).convert("RGB")
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001 - any decode failure is a bad upload
        raise HTTPException(400, f"could not read image: {e}") from e
    return np.asarray(im)[:, :, ::-1].copy()  # RGB -> BGR for OpenCV


def _rect(raw: str, width: int, height: int) -> tuple[int, int, int, int] | None:
    """Parse the user's box and clip it to the photo."""
    if not raw:
        return None
    try:
        x, y, w, h = (int(float(v)) for v in json.loads(raw))
    except (ValueError, TypeError) as e:
        raise HTTPException(400, "box must be [x, y, width, height]") from e
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(width, x + w), min(height, y + h)
    if x1 - x0 < 8 or y1 - y0 < 8:
        raise HTTPException(400, "box must cover at least 8 x 8 pixels of the photo")
    return x0, y0, x1 - x0, y1 - y0


def _points(raw: str) -> list[tuple[int, int]]:
    try:
        return [(int(float(x)), int(float(y))) for x, y in json.loads(raw or "[]")]
    except (ValueError, TypeError) as e:
        raise HTTPException(400, "points must be a JSON list of [x, y]") from e


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "version": __version__}


@app.post("/api/trace")
async def trace(
    image: UploadFile = File(...),
    rect: str = Form(""),
    fg: str = Form("[]"),
    bg: str = Form("[]"),
    edge: str = Form("[]"),
    size_mm: float = Form(90.0),
) -> dict:
    """Find the cookie and return its smoothed outline in mm and photo pixels.

    With three or more edge points the outline follows the photo's edges
    through those points; otherwise the box and clicks guide automatic tracing.
    """
    if not 20 <= size_mm <= 300:
        raise HTTPException(400, "size must be between 20 and 300 mm")
    img = _read_image(await _read_upload(image))
    h, w = img.shape[:2]
    edge_pts = [(min(w - 1, max(0, x)), min(h - 1, max(0, y))) for x, y in _points(edge)]
    if edge_pts:
        if len(edge_pts) < 3:
            raise HTTPException(400, "place at least 3 edge points")
        mask = edge_mask(img, edge_pts)
    else:
        mask = segment(img, _rect(rect, w, h), _points(fg), _points(bg))
    try:
        outline = mask_to_outline(mask, size_mm)
    except OutlineError as e:
        raise HTTPException(422, str(e)) from e
    poly = outline.polygon
    minx, miny, maxx, maxy = poly.bounds
    return {
        "outline_mm": np.round(np.array(poly.exterior.coords)[:-1], 3).tolist(),
        "outline_px": np.round(outline.to_pixels()[:-1], 1).tolist(),
        "width_mm": round(maxx - minx, 1),
        "height_mm": round(maxy - miny, 1),
        "check": check_outline(poly),
        # where the corner rules visibly changed the traced edge
        "rounded_mm": outline.rounded_mm,
        "rounded_px": [[round(outline.origin_px[0] + x * outline.px_per_mm, 1),
                        round(outline.origin_px[1] - y * outline.px_per_mm, 1), dep]
                       for x, y, dep in outline.rounded_mm],
        # maps mm back to photo pixels: px = origin + mm * px_per_mm (y down)
        "frame": {"px_per_mm": outline.px_per_mm, "origin_px": list(outline.origin_px)},
    }


@app.post("/api/stamp-lines")
async def stamp_lines(
    image: UploadFile = File(...),
    outline_mm: str = Form(...),
    frame: str = Form(...),
    level: float = Form(0.5),
    line_mm: float = Form(1.2),
) -> dict:
    """Icing lines inside a traced outline, for a matching stamp."""
    img = _read_image(await _read_upload(image))
    try:
        f = json.loads(frame)
        ppm, origin = float(f["px_per_mm"]), tuple(float(v) for v in f["origin_px"])
        poly = Polygon(json.loads(outline_mm))
        x0, y0, x1, y1 = poly.bounds
        # the photo is resampled to 6 px/mm, so these bound the work image size
        if not (np.isfinite([ppm, *origin, x0, y0, x1, y1]).all() and 0.5 <= ppm <= 1000
                and max(x1 - x0, y1 - y0) <= 300):
            raise ValueError("frame out of range")
        outline = Outline(poly, ppm, origin)
    except (ValueError, TypeError, KeyError) as e:
        raise HTTPException(400, "outline_mm and frame must come from /api/trace") from e
    if not 0.8 <= line_mm <= 3:
        raise HTTPException(400, "line width must be between 0.8 and 3 mm")
    lines = detail_lines(img, outline, level, line_mm)
    ox, oy = origin
    return {
        "lines_mm": rings(lines),
        "lines_px": rings(lines, lambda p: np.c_[ox + p[:, 0] * ppm, oy - p[:, 1] * ppm]),
    }


class CutterRequest(BaseModel):
    outline_mm: list[tuple[float, float]] = Field(min_length=16)
    nozzle_mm: float = Field(0.4, ge=0.2, le=1.0)
    height: float = Field(18.0, ge=8, le=40)
    flange_h: float = Field(2.4, ge=1.0, le=6)
    flange_w: float = Field(6.0, ge=2, le=20)
    tip_mm: float | None = Field(None, ge=0.3, le=2.0)
    spread: float = Field(0.0, ge=0, le=5)
    halo: float = Field(0.0, ge=0, le=20)        # grow the outline: a bubble border
    text: str = Field("", max_length=16)          # pressed into the underside of the base
    flip: bool = False                            # mirror image, for left/right pairs
    clearance: float = Field(2.0, ge=0.5, le=5)  # pusher plate gap, all round


def _request_geometry(req: CutterRequest) -> tuple[Polygon, CutterParams]:
    poly = Polygon(req.outline_mm).buffer(0)
    if poly.geom_type != "Polygon" or poly.area < 100:
        raise HTTPException(400, "outline must be one closed shape of at least 1 cm²")
    try:
        extra = {"wall_tip": req.tip_mm} if req.tip_mm else {}
        params = CutterParams.for_nozzle(req.nozzle_mm, height=req.height, flange_h=req.flange_h,
                                         flange_w=req.flange_w, spread=req.spread, halo=req.halo,
                                         text=req.text, **extra)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return (flipped(poly) if req.flip else orient(poly, 1.0)), params


def flipped(geom, about: Polygon | None = None):
    """Left-right mirror about the centre of `about` (default: geom itself),
    for the other one of a pair, like left and right mittens."""
    x0, _, x1, _ = (about or geom).bounds
    out = scale(geom, -1, 1, origin=((x0 + x1) / 2, 0))
    return orient(out, 1.0) if isinstance(out, Polygon) else out


def _stl(mesh, filename: str, notes: list[str]) -> Response:
    if not mesh.is_watertight:
        raise HTTPException(500, "generated mesh was not watertight; please report this photo")
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    w, h, _ = mesh.extents
    headers["X-CutterSnap-Size"] = f"{w:.1f}x{h:.1f}"
    if notes:
        headers["X-CutterSnap-Warning"] = " ".join(notes)
    return Response(mesh.export(file_type="stl"), media_type="model/stl", headers=headers)


@app.post("/api/check")
def check(req: CutterRequest) -> dict:
    """Radius check of the blade's cutting face, after any dough spread."""
    poly, params = _request_geometry(req)
    try:
        out = check_outline(cutting_face(poly, params.spread, params.halo))
        out["facet_mm"] = round(facet_error_mm(poly, params), 3)
        return out
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@app.post("/api/cutter")
def cutter(req: CutterRequest) -> Response:
    """Build the cutter STL from an outline (as returned by /api/trace)."""
    poly, params = _request_geometry(req)
    notes = params.warnings(req.nozzle_mm)
    try:
        mesh = build_cutter(poly, params, notes)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return _stl(mesh, "cookie-cutter.stl", notes)


class StampRequest(CutterRequest):
    lines_mm: list = Field(default_factory=list)  # as returned by /api/stamp-lines
    stamp_depth: float = Field(StampParams().relief_h, ge=1, le=4)  # how far the lines stand up


@app.post("/api/stamp")
def stamp(req: StampRequest) -> Response:
    """Build the matching stamp STL from an outline and its icing lines."""
    poly, params = _request_geometry(req)
    try:
        lines = from_rings(req.lines_mm)
        if req.flip:
            lines = flipped(lines, Polygon(req.outline_mm).buffer(0))
        mesh = build_stamp(poly, lines, params, StampParams(relief_h=req.stamp_depth))
    except (ValueError, TypeError, IndexError) as e:
        raise HTTPException(400, str(e)) from e
    return _stl(mesh, "cookie-stamp.stl", [])


@app.post("/api/set")
def size_set_zip(req: CutterRequest) -> Response:
    """The cutter and pusher at 5, 7.5 and 10 cm, with a print card, as a zip."""
    poly, params = _request_geometry(req)
    try:
        data, notes = size_set(poly, params, req.nozzle_mm)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    headers = {"Content-Disposition": 'attachment; filename="cookie-cutter-set.zip"'}
    if notes:
        headers["X-CutterSnap-Warning"] = " ".join(notes)
    return Response(data, media_type="application/zip", headers=headers)


@app.post("/api/pusher")
def pusher(req: CutterRequest) -> Response:
    """Build the matching pusher plate STL: pushes dough out of fine shapes."""
    poly, params = _request_geometry(req)
    try:
        mesh, notes = build_pusher(poly, params, PusherParams(clearance=req.clearance))
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return _stl(mesh, "cookie-pusher.stl", notes)
