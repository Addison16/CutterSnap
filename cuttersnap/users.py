"""Accounts: usernames and passwords kept in a small SQLite file next to the
saved designs, so CutterSnap stays self-contained with no outside services.

The first account made becomes the admin and takes over any designs saved
before accounts existed. The admin can turn sign-up off and manage users.
Passwords are stored as salted scrypt hashes; sign-in gives a random session
token, and only its SHA-256 is stored.

Forgot the admin password? From the host:

    docker exec -it cuttersnap python -m cuttersnap.users reset-password NAME
"""
from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
import sqlite3
import sys
import threading
import time
from contextlib import closing
from pathlib import Path

USERNAME = re.compile(r"[A-Za-z0-9_.-]{3,32}")
PASSWORD_MIN = 8
SESSION_DAYS = 30
COOKIE = "cuttersnap_session"
# sign-in attempts: this many failures per username within the window lock it briefly
MAX_FAILURES = 8
FAILURE_WINDOW = 15 * 60

_lock = threading.Lock()
_failures: dict[str, list[float]] = {}


class AuthError(ValueError):
    pass


def db_path() -> Path:
    d = Path(os.environ.get("CUTTERSNAP_DATA", "data"))
    d.mkdir(parents=True, exist_ok=True)
    return d / "cuttersnap.db"


def _db() -> sqlite3.Connection:
    con = sqlite3.connect(db_path(), timeout=10, isolation_level=None)
    con.row_factory = sqlite3.Row
    con.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,  -- ids never reused, so designs never change hands
            username TEXT NOT NULL UNIQUE COLLATE NOCASE,
            pw_hash TEXT NOT NULL,
            is_admin INTEGER NOT NULL DEFAULT 0,
            created_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS sessions (
            token_hash TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            expires_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        PRAGMA foreign_keys = ON;
    """)
    return con


# ---- passwords -----------------------------------------------------------------
def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    n, r, p = 2**14, 8, 1
    key = hashlib.scrypt(password.encode(), salt=salt, n=n, r=r, p=p, dklen=32)
    return f"scrypt${n}${r}${p}${salt.hex()}${key.hex()}"


def check_password(password: str, stored: str) -> bool:
    try:
        _, n, r, p, salt, key = stored.split("$")
        got = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=int(n), r=int(r), p=int(p),
                             dklen=len(key) // 2)
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(got.hex(), key)


def _check_new(username: str, password: str) -> None:
    if not USERNAME.fullmatch(username or ""):
        raise AuthError("usernames are 3 to 32 letters, digits, dots, dashes or underscores")
    if len(password or "") < PASSWORD_MIN:
        raise AuthError(f"passwords need at least {PASSWORD_MIN} characters")


# ---- users ---------------------------------------------------------------------
def _public(row) -> dict:
    return {"id": row["id"], "username": row["username"], "is_admin": bool(row["is_admin"]),
            "created_at": row["created_at"]}


def count() -> int:
    with closing(_db()) as con:
        return con.execute("SELECT COUNT(*) FROM users").fetchone()[0]


def signup_open() -> bool:
    with closing(_db()) as con:
        row = con.execute("SELECT value FROM settings WHERE key = 'signup_open'").fetchone()
    return row is None or row["value"] == "1"


def set_signup_open(open_: bool) -> None:
    with closing(_db()) as con:
        con.execute("INSERT INTO settings VALUES ('signup_open', ?) "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value", ("1" if open_ else "0",))


def create(username: str, password: str) -> dict:
    """New account. The first one is the admin; later ones need sign-up open."""
    _check_new(username, password)
    pw = hash_password(password)
    with _lock, closing(_db()) as con:
        con.execute("BEGIN IMMEDIATE")
        try:
            first = con.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0
            if not first:
                row = con.execute("SELECT value FROM settings WHERE key = 'signup_open'").fetchone()
                if row is not None and row["value"] != "1":
                    raise AuthError("sign-up is turned off; ask the admin for an account")
            cur = con.execute("INSERT INTO users (username, pw_hash, is_admin, created_at) VALUES (?, ?, ?, ?)",
                              (username, pw, int(first), int(time.time())))
            con.execute("COMMIT")
        except sqlite3.IntegrityError:
            con.execute("ROLLBACK")
            raise AuthError("that username is taken") from None
        except BaseException:
            con.execute("ROLLBACK")
            raise
        return _public(con.execute("SELECT * FROM users WHERE id = ?", (cur.lastrowid,)).fetchone())


def first_admin_id() -> int | None:
    with closing(_db()) as con:
        row = con.execute("SELECT id FROM users WHERE is_admin = 1 ORDER BY id LIMIT 1").fetchone()
    return row["id"] if row else None


def all_users() -> list[dict]:
    with closing(_db()) as con:
        return [_public(r) for r in con.execute("SELECT * FROM users ORDER BY id")]


def get(user_id: int) -> dict | None:
    with closing(_db()) as con:
        row = con.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return _public(row) if row else None


def delete(user_id: int) -> None:
    with closing(_db()) as con:
        row = con.execute("SELECT is_admin FROM users WHERE id = ?", (user_id,)).fetchone()
        if row is None:
            raise KeyError(user_id)
        if row["is_admin"] and con.execute("SELECT COUNT(*) FROM users WHERE is_admin = 1").fetchone()[0] == 1:
            raise AuthError("the last admin cannot be deleted")
        con.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
        con.execute("DELETE FROM users WHERE id = ?", (user_id,))


def set_password(user_id: int, password: str) -> None:
    """New password; signs the user out everywhere."""
    if len(password or "") < PASSWORD_MIN:
        raise AuthError(f"passwords need at least {PASSWORD_MIN} characters")
    with closing(_db()) as con:
        if con.execute("UPDATE users SET pw_hash = ? WHERE id = ?", (hash_password(password), user_id)).rowcount == 0:
            raise KeyError(user_id)
        con.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))


# ---- sign-in -------------------------------------------------------------------
def _limited(username: str) -> bool:
    now = time.time()
    with _lock:
        recent = [t for t in _failures.get(username.lower(), []) if now - t < FAILURE_WINDOW]
        _failures[username.lower()] = recent
        return len(recent) >= MAX_FAILURES


def _failed(username: str) -> None:
    with _lock:
        _failures.setdefault(username.lower(), []).append(time.time())


def verify(user_id: int, password: str) -> bool:
    """Is this the user's password (for changing it)? Counts towards the sign-in limit."""
    with closing(_db()) as con:
        row = con.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if row is None or _limited(row["username"]):
        return False
    if check_password(password or "", row["pw_hash"]):
        return True
    _failed(row["username"])
    return False


def login(username: str, password: str) -> tuple[dict, str]:
    """Check a password; returns the user and a new session token."""
    if _limited(username or ""):
        raise AuthError("too many wrong passwords; wait a few minutes and try again")
    with closing(_db()) as con:
        row = con.execute("SELECT * FROM users WHERE username = ?", (username or "",)).fetchone()
    # hash even for unknown names, so timing doesn't reveal which usernames exist
    ok = check_password(password or "", row["pw_hash"] if row else _DUMMY)
    if not (row and ok):
        _failed(username or "")
        raise AuthError("wrong username or password")
    return _public(row), new_session(row["id"])


def new_session(user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    with closing(_db()) as con:
        con.execute("DELETE FROM sessions WHERE expires_at < ?", (int(time.time()),))
        con.execute("INSERT INTO sessions VALUES (?, ?, ?)",
                    (_token_hash(token), user_id, int(time.time()) + SESSION_DAYS * 86400))
    return token


def session_user(token: str | None) -> dict | None:
    if not token:
        return None
    with closing(_db()) as con:
        row = con.execute("SELECT u.* FROM sessions s JOIN users u ON u.id = s.user_id "
                          "WHERE s.token_hash = ? AND s.expires_at > ?",
                          (_token_hash(token), int(time.time()))).fetchone()
    return _public(row) if row else None


def logout(token: str | None) -> None:
    if token:
        with closing(_db()) as con:
            con.execute("DELETE FROM sessions WHERE token_hash = ?", (_token_hash(token),))


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


_DUMMY = hash_password(secrets.token_hex(8))


# ---- command line: password resets for a locked-out admin --------------------------
def main(argv: list[str] | None = None) -> None:
    import getpass

    args = sys.argv[1:] if argv is None else argv
    if len(args) == 2 and args[0] == "reset-password":
        name = args[1]
        match = [u for u in all_users() if u["username"].lower() == name.lower()]
        if not match:
            sys.exit(f"no user called {name}")
        pw = getpass.getpass(f"New password for {match[0]['username']}: ")
        if pw != getpass.getpass("Again: "):
            sys.exit("the passwords did not match")
        set_password(match[0]["id"], pw)
        print("Password changed; that user is signed out everywhere.")
    elif args == ["list"]:
        for u in all_users():
            print(f"{u['username']}{'  (admin)' if u['is_admin'] else ''}")
    else:
        sys.exit("usage: python -m cuttersnap.users reset-password NAME | list")


if __name__ == "__main__":
    main()
