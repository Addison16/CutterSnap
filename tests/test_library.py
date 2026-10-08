import json

import cv2


def _project(star_photo, client):
    img, _ = star_photo
    png = cv2.imencode(".png", img)[1].tobytes()
    tr = client.post("/api/trace", files={"image": ("s.png", png, "image/png")},
                     data={"rect": json.dumps([130, 50, 540, 520]), "size_mm": "70"}).json()
    return {"cuttersnap": 1, "size_mm": 70, "outline_mm": tr["outline_mm"], "outline_px": tr["outline_px"],
            "cutter": {"nozzle_mm": 0.4, "text": "SC", "flip": True}, "stamp": {"on": False}}


def test_saved_design_downloads_from_any_device(client, star_photo):
    proj = _project(star_photo, client)
    assert client.get("/api/designs").json() == []
    saved = client.post("/api/designs", json={"name": "  Star   cookie ", "project": proj}).json()
    assert saved["name"] == "Star cookie" and saved["size_mm"] == 70 and not saved["stamp"]
    listed = client.get("/api/designs").json()
    assert [d["id"] for d in listed] == [saved["id"]] and len(listed[0]["thumb_mm"]) <= 70
    # opening it gives back exactly what was saved, outline on the photo included
    assert client.get(f"/api/designs/{saved['id']}").json()["project"] == proj
    res = client.get(f"/api/designs/{saved['id']}/cutter.stl")
    assert res.status_code == 200 and "star-cookie-cutter.stl" in res.headers["content-disposition"]
    w, h = map(float, res.headers["x-cutterSnap-size"].split("x"))
    assert max(w, h) > 70  # the cookie is 70 mm inside; the base adds to that
    assert client.get(f"/api/designs/{saved['id']}/pusher.stl").status_code == 200
    assert client.get(f"/api/designs/{saved['id']}/stamp.stl").status_code == 400  # no stamp lines
    assert client.delete(f"/api/designs/{saved['id']}").json()["ok"]
    assert client.get("/api/designs").json() == []


def test_switched_off_stamp_is_not_offered(client, star_photo):
    proj = _project(star_photo, client)
    proj["stamp"] = {"on": False, "lines_mm": [[[[30, 30], [40, 30], [40, 40]]]]}
    saved = client.post("/api/designs", json={"name": "x", "project": proj}).json()
    assert not saved["stamp"]


def test_library_refuses_bad_input(client):
    assert client.get("/api/designs/../../etc/passwd").status_code == 404
    assert client.get("/api/designs/zzzz").status_code == 404
    assert client.get("/api/designs/0123456789abcdef/cutter.stl").status_code == 404
    assert client.get("/api/designs/0123456789abcdef/secret.stl").status_code == 404
    bad = {"name": "x", "project": {"cuttersnap": 1, "outline_mm": [[0, 0]] * 20}}
    assert client.post("/api/designs", json=bad).status_code == 400
    assert client.post("/api/designs", content=b"x" * (3 * 1024 * 1024)).status_code == 413
