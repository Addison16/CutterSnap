"""Saved designs: projects kept on the server, so a design made on a phone
is waiting on any device where its owner signs in.

Each design is one JSON file named by a random id, holding a project in the
same format as Save project. Set CUTTERSNAP_DATA to choose the folder (the
Docker image keeps it in a volume). Each design records its owner's user
id; designs saved before accounts existed belong to the first admin.
"""
from __future__ import annotations

import json
import os
import re
import secrets
import time
from pathlib import Path

from . import users
from .project import Project

MAX_DESIGNS = 500   # per user
NAME_MAX = 60
ID = re.compile(r"[0-9a-f]{16}")


def folder() -> Path:
    d = Path(os.environ.get("CUTTERSNAP_DATA", "data")) / "designs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _path(design_id: str) -> Path:
    if not ID.fullmatch(design_id):
        raise KeyError(design_id)
    return folder() / f"{design_id}.json"


def save(owner: int, name: str, project: dict) -> dict:
    """Store a user's project (checked by loading it) and return its list entry."""
    proj = Project.from_json(project)
    proj.polygon()  # refuse outlines that cannot be built
    proj.params()
    if len(designs(owner)) >= MAX_DESIGNS:
        raise ValueError(f"the library is full ({MAX_DESIGNS} designs); delete some first")
    name = " ".join(str(name).split())[:NAME_MAX] or "Cookie"
    design_id = secrets.token_hex(8)
    # kept as sent, so opening it restores the page exactly (outline on the photo, stamp lines)
    entry = {"id": design_id, "owner": owner, "name": name, "saved_at": int(time.time()), "project": project}
    tmp = folder() / f".{design_id}.tmp"
    tmp.write_text(json.dumps(entry))
    tmp.replace(_path(design_id))
    # checked after writing: deleting an account removes the user before their designs, so a
    # save racing the deletion is either swept up by it or sees the user gone here
    if users.get(owner) is None:
        _path(design_id).unlink(missing_ok=True)
        raise ValueError("this account no longer exists")
    return _summary(entry)


def _owner(entry: dict, admin: int | None) -> int | None:
    # saved before accounts existed: the first admin's
    return entry.get("owner", admin)


def load(design_id: str, owner: int) -> dict:
    """A design, if it is this user's (anyone else's reads as missing)."""
    try:
        entry = json.loads(_path(design_id).read_text())
    except FileNotFoundError:
        raise KeyError(design_id) from None
    if _owner(entry, users.first_admin_id()) != owner:
        raise KeyError(design_id)
    return entry


def project(design_id: str, owner: int) -> Project:
    return Project.from_json(load(design_id, owner)["project"])


def delete(design_id: str, owner: int) -> None:
    load(design_id, owner)
    try:
        _path(design_id).unlink()
    except FileNotFoundError:
        raise KeyError(design_id) from None


def delete_all(owner: int) -> int:
    """Remove every design of a user (when the account is deleted)."""
    n = 0
    for d in designs(owner):
        delete(d["id"], owner)
        n += 1
    return n


def designs(owner: int) -> list[dict]:
    """A user's designs, newest first, each with a small outline for a thumbnail."""
    admin = users.first_admin_id()
    out = []
    for f in folder().glob("*.json"):
        try:
            entry = json.loads(f.read_text())
            if _owner(entry, admin) == owner:
                out.append(_summary(entry))
        except (ValueError, KeyError, TypeError):
            continue  # a damaged file should not hide the rest
    return sorted(out, key=lambda e: -e["saved_at"])


def _has_stamp(stamp: dict) -> bool:
    # lines found earlier can stay in a project whose stamp was then switched off
    return bool(stamp.get("on", True) and stamp.get("lines_mm"))


def _summary(entry: dict) -> dict:
    p = entry["project"]
    pts = p["outline_mm"]
    step = max(1, len(pts) // 60)
    return {
        "id": entry["id"], "name": entry["name"], "saved_at": entry["saved_at"],
        "size_mm": p.get("size_mm"), "stamp": _has_stamp(p.get("stamp") or {}),
        "thumb_mm": [[round(x, 1), round(y, 1)] for x, y in pts[::step]],
    }
