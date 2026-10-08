import json

import cv2
import pytest

from cuttersnap.cli import main
from cuttersnap.project import Project


def test_project_rebuilds_identical_stl(tmp_path, star_photo):
    img, _ = star_photo
    photo = tmp_path / "star.png"
    cv2.imwrite(str(photo), img)
    main([str(photo), str(tmp_path / "a.stl"), "--box", "130,50,540,520", "--size", "80",
          "--save-project", str(tmp_path / "p.json")])
    data = json.loads((tmp_path / "p.json").read_text())
    assert data["cuttersnap"] == 1 and len(data["photo"]["sha256"]) == 64
    assert data["marks"]["box"] == [130, 50, 540, 520]
    main([str(tmp_path / "p.json"), str(tmp_path / "b.stl")])
    assert (tmp_path / "a.stl").read_bytes() == (tmp_path / "b.stl").read_bytes()


def test_project_round_trip():
    p = Project(outline_mm=[[i, i * i % 7] for i in range(20)], edge=[[1, 2], [3, 4], [5, 6]], spread=1.0,
                halo=2.0, text="AB", flip=True, stamp_depth=3.0)
    q = Project.from_json(json.loads(json.dumps(p.to_json())))
    assert q == p


def test_project_options_on_the_command_line(tmp_path, capsys):
    from shapely.geometry import Point

    ring = list(Point(45, 45).buffer(40, 64).exterior.coords)[:-1]
    Project(outline_mm=[[round(x, 3), round(y, 3)] for x, y in ring]).save(tmp_path / "c.json")
    main([str(tmp_path / "c.json"), str(tmp_path / "a.stl")])
    main([str(tmp_path / "c.json"), str(tmp_path / "b.stl"), "--initials", "AH", "--halo", "3"])
    out = capsys.readouterr().out
    assert "did not fit" not in out and "facets within" in out
    import trimesh

    a, b = trimesh.load(tmp_path / "a.stl"), trimesh.load(tmp_path / "b.stl")
    assert b.extents[0] == pytest.approx(a.extents[0] + 6, abs=0.3)
