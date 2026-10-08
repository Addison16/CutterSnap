import json
import math
import time

import pytest
from fastapi.testclient import TestClient

from cuttersnap import library, users
from cuttersnap.api import app
from cuttersnap.project import FORMAT

# a 60 mm circle, as a cutter request and as a saved project
CIRCLE = [[30 + 30 * math.cos(a / 32 * math.tau), 30 + 30 * math.sin(a / 32 * math.tau)] for a in range(32)]
CUTTER = {"outline_mm": CIRCLE}
PROJECT = {"cuttersnap": FORMAT, "outline_mm": CIRCLE, "size_mm": 60}


def _signup(c, name, pw="sugar-cookies"):
    return c.post("/api/signup", json={"username": name, "password": pw})


def test_first_account_is_admin_and_everything_else_needs_sign_in(anon):
    me = anon.get("/api/me").json()
    assert me == {"user": None, "setup": True, "signup_open": True}
    assert anon.get("/api/health").status_code == 200
    assert "CutterSnap" in anon.get("/").text
    for method, path in [("get", "/api/designs"), ("post", "/api/cutter"), ("post", "/api/trace"),
                         ("get", "/api/admin/users")]:
        assert getattr(anon, method)(path).status_code == 401, path

    res = _signup(anon, "baker")
    assert res.status_code == 200, res.text
    cookie = res.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie
    me = anon.get("/api/me").json()
    assert me["user"]["username"] == "baker" and me["user"]["is_admin"] and not me["setup"]
    assert "pw_hash" not in json.dumps(me)
    assert anon.post("/api/cutter", json=CUTTER).status_code == 200

    assert anon.post("/api/logout").json()["ok"]
    assert anon.get("/api/me").json()["user"] is None
    assert anon.get("/api/designs").status_code == 401


def test_passwords_are_hashed_and_sessions_stored_as_hashes(client, tmp_path):
    import sqlite3

    con = sqlite3.connect(tmp_path / "cuttersnap.db")
    (pw_hash,) = con.execute("SELECT pw_hash FROM users").fetchone()
    assert pw_hash.startswith("scrypt$") and "sugar-cookies" not in pw_hash
    (token_hash,) = con.execute("SELECT token_hash FROM sessions").fetchone()
    assert token_hash != client.cookies.get(users.COOKIE)
    assert users.check_password("sugar-cookies", pw_hash) and not users.check_password("sugar", pw_hash)


def test_sign_in_and_bad_input(anon):
    assert _signup(anon, "ab").status_code == 400                  # too short a name
    assert _signup(anon, "baker", "short").status_code == 400      # too short a password
    assert _signup(anon, "baker").status_code == 200
    anon.post("/api/logout")
    assert _signup(anon, "BAKER").json()["detail"] == "that username is taken"
    assert anon.post("/api/login", json={"username": "baker", "password": "wrong-one"}).status_code == 401
    assert anon.post("/api/login", json={"username": "nobody", "password": "sugar-cookies"}).status_code == 401
    res = anon.post("/api/login", json={"username": " Baker ", "password": "sugar-cookies"})
    assert res.status_code == 200 and res.json()["user"]["username"] == "baker"


def test_wrong_passwords_are_limited(anon):
    _signup(anon, "baker")
    anon.post("/api/logout")
    for _ in range(users.MAX_FAILURES):
        anon.post("/api/login", json={"username": "baker", "password": "guessing"})
    res = anon.post("/api/login", json={"username": "baker", "password": "sugar-cookies"})
    assert res.status_code == 401 and "too many" in res.json()["detail"]
    # the window passes
    users._failures["baker"] = [time.time() - users.FAILURE_WINDOW - 1] * users.MAX_FAILURES
    assert anon.post("/api/login", json={"username": "baker", "password": "sugar-cookies"}).status_code == 200


def test_each_user_sees_only_their_own_designs(client, tmp_path):
    other = TestClient(app)
    assert _signup(other, "neighbour").status_code == 200
    assert not other.get("/api/me").json()["user"]["is_admin"]

    mine = client.post("/api/designs", json={"name": "Mine", "project": PROJECT}).json()
    theirs = other.post("/api/designs", json={"name": "Theirs", "project": PROJECT}).json()
    assert [d["name"] for d in client.get("/api/designs").json()] == ["Mine"]
    assert [d["name"] for d in other.get("/api/designs").json()] == ["Theirs"]
    # someone else's design reads as missing, for every way in
    assert other.get(f"/api/designs/{mine['id']}").status_code == 404
    assert other.get(f"/api/designs/{mine['id']}/cutter.stl").status_code == 404
    assert other.delete(f"/api/designs/{mine['id']}").status_code == 404
    assert client.get(f"/api/designs/{mine['id']}/cutter.stl").status_code == 200
    assert client.delete(f"/api/designs/{theirs['id']}").status_code == 404
    assert (tmp_path / "designs" / f"{theirs['id']}.json").exists()


def test_designs_from_before_accounts_go_to_the_first_account(anon, tmp_path):
    folder = tmp_path / "designs"
    folder.mkdir()
    old = {"id": "0123456789abcdef", "name": "Old star", "saved_at": 1, "project": PROJECT}
    (folder / "0123456789abcdef.json").write_text(json.dumps(old))

    _signup(anon, "baker")
    assert [d["name"] for d in anon.get("/api/designs").json()] == ["Old star"]
    second = TestClient(app)
    _signup(second, "neighbour")
    assert second.get("/api/designs").json() == []
    assert second.get("/api/designs/0123456789abcdef").status_code == 404


def test_admin_turns_sign_up_off_and_manages_users(client):
    other = TestClient(app)
    _signup(other, "neighbour")
    assert other.get("/api/admin/users").status_code == 403
    assert other.post("/api/admin/signup", json={"signup_open": False}).status_code == 403

    assert client.post("/api/admin/signup", json={"signup_open": False}).json() == {"signup_open": False}
    late = TestClient(app)
    assert late.get("/api/me").json()["signup_open"] is False
    res = _signup(late, "latecomer")
    assert res.status_code == 400 and "turned off" in res.json()["detail"]

    listed = client.get("/api/admin/users").json()
    assert [u["username"] for u in listed["users"]] == ["baker", "neighbour"]
    nid = listed["users"][1]["id"]

    # a password reset signs them out
    assert client.post(f"/api/admin/users/{nid}/password", json={"password": "new-password"}).json()["ok"]
    assert other.get("/api/designs").status_code == 401
    assert other.post("/api/login", json={"username": "neighbour", "password": "new-password"}).status_code == 200

    other.post("/api/designs", json={"name": "Theirs", "project": PROJECT})
    me = client.get("/api/me").json()["user"]["id"]
    assert client.delete(f"/api/admin/users/{me}").status_code == 400
    res = client.delete(f"/api/admin/users/{nid}").json()
    assert res == {"ok": True, "designs_deleted": 1}
    assert other.get("/api/designs").status_code == 401
    # a later account never inherits the deleted one's id
    client.post("/api/admin/signup", json={"signup_open": True})
    _signup(late, "latecomer")
    assert late.get("/api/me").json()["user"]["id"] != nid


def test_last_admin_cannot_be_deleted(client):
    with pytest.raises(users.AuthError):
        users.delete(users.first_admin_id())


def test_change_own_password(client):
    other = TestClient(app)
    other.post("/api/login", json={"username": "baker", "password": "sugar-cookies"})
    res = client.post("/api/password", json={"current": "nope-nope", "password": "ginger-snaps"})
    assert res.status_code == 400
    res = client.post("/api/password", json={"current": "sugar-cookies", "password": "ginger-snaps"})
    assert res.status_code == 200
    assert client.get("/api/designs").status_code == 200    # this device stays signed in
    assert other.get("/api/designs").status_code == 401     # the other one is signed out


def test_writes_from_another_site_are_refused(client):
    res = client.post("/api/cutter", json=CUTTER, headers={"origin": "https://evil.example"})
    assert res.status_code == 403
    assert client.post("/api/cutter", json=CUTTER, headers={"origin": "http://testserver"}).status_code == 200
    # behind a proxy that rewrites Host
    res = client.post("/api/cutter", json=CUTTER, headers={"origin": "https://cookies.example",
                                                            "x-forwarded-host": "cookies.example"})
    assert res.status_code == 200


def test_reset_password_from_the_command_line(client, monkeypatch, capsys):
    pw = iter(["from-the-shell", "from-the-shell"])
    monkeypatch.setattr("getpass.getpass", lambda prompt="": next(pw))
    users.main(["reset-password", "Baker"])
    assert "signed out" in capsys.readouterr().out
    assert client.get("/api/designs").status_code == 401
    users.main(["list"])
    assert "baker  (admin)" in capsys.readouterr().out
    assert library.designs(users.first_admin_id()) == []


def test_a_save_that_finishes_after_its_account_is_deleted_leaves_nothing(client, tmp_path):
    other = TestClient(app)
    _signup(other, "neighbour")
    nid = other.get("/api/me").json()["user"]["id"]
    client.delete(f"/api/admin/users/{nid}")
    # the request had already passed sign-in when the account went
    with pytest.raises(ValueError, match="no longer exists"):
        library.save(nid, "Late", PROJECT)
    assert list((tmp_path / "designs").glob("*.json")) == []
