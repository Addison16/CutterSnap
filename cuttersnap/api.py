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
from shapely.geometry import Polygon
from shapely.ops import orient

from . import __version__
from .cutter import CutterParams, build_cutter
from .outline import OutlineError, check_outline, mask_to_outline
from .segment import segment

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
    size_mm: float = Form(90.0),
) -> dict:
    """Find the cookie and return its smoothed outline in mm and photo pixels."""
    if not 20 <= size_mm <= 300:
        raise HTTPException(400, "size must be between 20 and 300 mm")
    img = _read_image(await _read_upload(image))
    r = _rect(rect, img.shape[1], img.shape[0])
    mask = segment(img, r, _points(fg), _points(bg))
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
    }


class CutterRequest(BaseModel):
    outline_mm: list[tuple[float, float]] = Field(min_length=16)
    nozzle_mm: float = Field(0.4, ge=0.2, le=1.0)
    height: float = Field(18.0, ge=8, le=40)
    flange_h: float = Field(2.4, ge=1.0, le=6)
    flange_w: float = Field(6.0, ge=2, le=20)
    tip_mm: float | None = Field(None, ge=0.3, le=2.0)
    spread: float = Field(0.0, ge=0, le=5)


@app.post("/api/cutter")
def cutter(req: CutterRequest) -> Response:
    """Build the cutter STL from an outline (as returned by /api/trace)."""
    poly = Polygon(req.outline_mm).buffer(0)
    if poly.geom_type != "Polygon" or poly.area < 100:
        raise HTTPException(400, "outline must be one closed shape of at least 1 cm²")
    try:
        extra = {"wall_tip": req.tip_mm} if req.tip_mm else {}
        params = CutterParams.for_nozzle(req.nozzle_mm, height=req.height, flange_h=req.flange_h,
                                         flange_w=req.flange_w, spread=req.spread, **extra)
        mesh = build_cutter(orient(poly, 1.0), params)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    if not mesh.is_watertight:
        raise HTTPException(500, "generated mesh was not watertight; please report this photo")
    headers = {"Content-Disposition": 'attachment; filename="cookie-cutter.stl"'}
    warnings = params.warnings(req.nozzle_mm)
    if warnings:
        headers["X-CutterSnap-Warning"] = " ".join(warnings)
    return Response(mesh.export(file_type="stl"), media_type="model/stl", headers=headers)
