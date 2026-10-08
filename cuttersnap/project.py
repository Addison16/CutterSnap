"""Project files: everything needed to rebuild a cutter, as JSON.

Once traced, the outline is the source of truth, not the photo: building
from a saved project gives the same STL every time. The photo's marks are
kept too, so the outline can be traced again later.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

FORMAT = 1


@dataclass
class Project:
    outline_mm: list[list[float]]
    size_mm: float = 90.0
    photo_name: str = ""
    photo_sha256: str = ""
    box: list[int] | None = None
    cookie: list[list[int]] = field(default_factory=list)
    not_cookie: list[list[int]] = field(default_factory=list)
    edge: list[list[int]] = field(default_factory=list)
    nozzle_mm: float = 0.4
    height: float = 18.0
    flange_w: float = 6.0
    spread: float = 0.0
    stamp_lines_mm: list = field(default_factory=list)  # [[exterior, hole, ...], ...]

    def to_json(self) -> dict:
        d = asdict(self)
        return {
            "cuttersnap": FORMAT,
            "photo": {"name": d.pop("photo_name"), "sha256": d.pop("photo_sha256")},
            "marks": {k: d.pop(k) for k in ("box", "cookie", "not_cookie", "edge")},
            "size_mm": d.pop("size_mm"),
            "cutter": {k: d.pop(k) for k in ("nozzle_mm", "height", "flange_w", "spread")},
            "outline_mm": d.pop("outline_mm"),
            "stamp": {"on": bool(self.stamp_lines_mm), "lines_mm": d.pop("stamp_lines_mm")},
        }

    @classmethod
    def from_json(cls, d: dict) -> Project:
        if d.get("cuttersnap") != FORMAT:
            raise ValueError("not a CutterSnap project file (or a newer version)")
        if len(d.get("outline_mm") or []) < 16:
            raise ValueError("project has no traced outline")
        photo, marks, cutter = d.get("photo", {}), d.get("marks", {}), d.get("cutter", {})
        return cls(outline_mm=d["outline_mm"], size_mm=d.get("size_mm", 90.0),
                   photo_name=photo.get("name", ""), photo_sha256=photo.get("sha256", ""),
                   **{k: marks[k] for k in ("box", "cookie", "not_cookie", "edge") if k in marks},
                   **{k: cutter[k] for k in ("nozzle_mm", "height", "flange_w", "spread") if k in cutter},
                   stamp_lines_mm=(d.get("stamp") or {}).get("lines_mm") or [])

    def save(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.to_json(), indent=1))

    @classmethod
    def load(cls, path: str | Path) -> Project:
        return cls.from_json(json.loads(Path(path).read_text()))


def sha256_file(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()
