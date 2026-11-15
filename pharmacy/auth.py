"""Pharmacist accounts.

- Passwords are stored only as salted scrypt hashes (never in plain text).
- 5 wrong passwords lock the account for 5 minutes.
- Every login, failure, lockout and account change goes to the audit log.
- The approving pharmacist is now the logged-in account, not a typed name.
"""
import hashlib
import hmac
import secrets
import time
from datetime import datetime, timedelta

from .db import log, now

MIN_PASSWORD = 8
MAX_PASSWORD = 256  # bounds the hashing work per attempt
MAX_FAILURES = 5
LOCK_MINUTES = 5
GLOBAL_FAILS_PER_MINUTE = 20  # across all usernames: stops guessing spread over many accounts
FAIL_DELAY_SECONDS = 1.0
_N, _R, _P = 2 ** 14, 8, 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
    full_name TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    is_admin INTEGER NOT NULL DEFAULT 0,
    active INTEGER NOT NULL DEFAULT 1,
    failed_attempts INTEGER NOT NULL DEFAULT 0,
    locked_until TEXT,
    created_at TEXT NOT NULL,
    last_login TEXT
);
"""


class AuthError(Exception):
    pass


def ensure_schema(conn):
    conn.executescript(SCHEMA)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(users)")}
    if "session_version" not in cols:  # databases created before this column existed
        conn.execute("ALTER TABLE users ADD COLUMN session_version INTEGER NOT NULL DEFAULT 0")
        conn.commit()


def _fail(conn, actor, action, message, details=None):
    log(conn, actor, action, details)
    conn.commit()
    time.sleep(FAIL_DELAY_SECONDS)  # slows down automated guessing
    raise AuthError(message)


def _recent_failures(conn) -> int:
    since = (datetime.now() - timedelta(minutes=1)).isoformat(timespec="seconds")
    return conn.execute("SELECT COUNT(*) FROM audit_log WHERE action LIKE 'failed login%' AND at >= ?",
                        (since,)).fetchone()[0]


def is_admin(conn, user_id: int) -> bool:
    row = conn.execute("SELECT is_admin, active FROM users WHERE id = ?", (user_id,)).fetchone()
    return bool(row and row["is_admin"] and row["active"])


def session_valid(conn, user: dict) -> bool:
    """Checked on every page load: the account still exists, is active, and nothing (password change,
    deactivation) has invalidated sessions since sign-in."""
    row = conn.execute("SELECT active, session_version, is_admin FROM users WHERE id = ?", (user["id"],)).fetchone()
    if not row or not row["active"] or row["session_version"] != user.get("session_version"):
        return False
    user["is_admin"] = bool(row["is_admin"])  # always use the current role, not the one at sign-in
    return True


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=_N, r=_R, p=_P, dklen=32)
    return f"scrypt${_N}${_R}${_P}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, n, r, p, salt, digest = stored.split("$")
        if algo != "scrypt":
            return False
        calc = hashlib.scrypt(password.encode("utf-8"), salt=bytes.fromhex(salt), n=int(n), r=int(r), p=int(p),
                              dklen=len(bytes.fromhex(digest)))
        return hmac.compare_digest(calc, bytes.fromhex(digest))
    except (ValueError, TypeError):
        return False


def _check_password_rules(password: str, username: str):
    if len(password) < MIN_PASSWORD:
        raise AuthError(f"Password must be at least {MIN_PASSWORD} characters.")
    if len(password) > MAX_PASSWORD:
        raise AuthError(f"Password must be at most {MAX_PASSWORD} characters.")
    if password.lower() == username.lower():
        raise AuthError("Password can't be the same as the username.")


def has_users(conn) -> bool:
    ensure_schema(conn)
    return conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] > 0


def create_user(conn, username: str, full_name: str, password: str, is_admin=False, actor="system", by_admin=False):
    """by_admin: the caller has verified an administrator is doing this. Only the very first account
    (when none exist) can be created without one."""
    ensure_schema(conn)
    if has_users(conn) and not by_admin:
        raise AuthError("Only an administrator can add accounts.")
    username, full_name = (username or "").strip(), (full_name or "").strip()
    if not username or not full_name:
        raise AuthError("Username and full name are required.")
    if len(full_name) > 80:
        raise AuthError("Full name is too long (80 characters at most).")
    if not username.replace(".", "").replace("_", "").replace("-", "").isalnum() or len(username) > 32:
        raise AuthError("Username: letters, numbers, dots, dashes or underscores, 32 characters at most.")
    _check_password_rules(password, username)
    if conn.execute("SELECT 1 FROM users WHERE username = ?", (username,)).fetchone():
        raise AuthError("That username is taken.")
    conn.execute(
        "INSERT INTO users (username, full_name, password_hash, is_admin, created_at) VALUES (?, ?, ?, ?, ?)",
        (username, full_name, hash_password(password), 1 if is_admin else 0, now()),
    )
    log(conn, actor, "created account", {"username": username, "admin": bool(is_admin)})
    conn.commit()


def authenticate(conn, username: str, password: str) -> dict:
    """Returns the user row as a dict, or raises AuthError with a message safe to show."""
    ensure_schema(conn)
    generic = "Wrong username or password."
    username, password = (username or "").strip()[:64], (password or "")[:MAX_PASSWORD]
    if _recent_failures(conn) >= GLOBAL_FAILS_PER_MINUTE:
        _fail(conn, "unknown", "login refused: too many attempts", "Too many sign-in attempts. Wait a minute and try again.")
    row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    if row is None or not row["active"]:
        verify_password(password, hash_password("timing-equaliser"))  # same work whether or not the user exists
        _fail(conn, "unknown", "failed login", generic, {"username": username[:32]})
    if row["locked_until"] and row["locked_until"] > now():
        _fail(conn, row["username"], "login refused: account locked",
              f"Too many wrong passwords. Try again after {row['locked_until'][11:16]}.")
    if not verify_password(password, row["password_hash"]):
        fails = row["failed_attempts"] + 1
        locked = None
        if fails >= MAX_FAILURES:
            locked = (datetime.now() + timedelta(minutes=LOCK_MINUTES)).isoformat(timespec="seconds")
            fails = 0
        conn.execute("UPDATE users SET failed_attempts = ?, locked_until = ? WHERE id = ?", (fails, locked, row["id"]))
        _fail(conn, row["username"], "failed login" + (" - account locked" if locked else ""), generic)
    conn.execute("UPDATE users SET failed_attempts = 0, locked_until = NULL, last_login = ? WHERE id = ?",
                 (now(), row["id"]))
    log(conn, row["username"], "logged in")
    conn.commit()
    return {"id": row["id"], "username": row["username"], "full_name": row["full_name"],
            "is_admin": bool(row["is_admin"]), "session_version": row["session_version"]}


def change_password(conn, user_id: int, current: str, new: str):
    """Returns the new session version, so the current session stays signed in while all others end."""
    row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if row is None or not verify_password((current or "")[:MAX_PASSWORD], row["password_hash"]):
        _fail(conn, row["username"] if row else "unknown", "failed password change", "Current password is wrong.")
    _check_password_rules(new, row["username"])
    conn.execute("UPDATE users SET password_hash = ?, session_version = session_version + 1 WHERE id = ?",
                 (hash_password(new), user_id))
    log(conn, row["username"], "changed password (other sessions signed out)")
    conn.commit()
    return row["session_version"] + 1


def set_active(conn, user_id: int, active: bool, actor: str, by_admin=False):
    if not by_admin:
        raise AuthError("Only an administrator can change accounts.")
    row = conn.execute("SELECT username, is_admin FROM users WHERE id = ?", (user_id,)).fetchone()
    if row is None:
        raise AuthError("No such account.")
    if not active and row["is_admin"]:
        admins = conn.execute("SELECT COUNT(*) FROM users WHERE is_admin = 1 AND active = 1").fetchone()[0]
        if admins <= 1:
            raise AuthError("Can't deactivate the last administrator.")
    # Bumping session_version signs the account out everywhere immediately.
    conn.execute("UPDATE users SET active = ?, session_version = session_version + 1 WHERE id = ?",
                 (1 if active else 0, user_id))
    log(conn, actor, "activated account" if active else "deactivated account", {"username": row["username"]})
    conn.commit()


def list_users(conn):
    ensure_schema(conn)
    return conn.execute("SELECT id, username, full_name, is_admin, active, last_login FROM users ORDER BY username").fetchall()
