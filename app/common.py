"""Web plumbing shared by every route: templates, cookies, host login lookup, game ownership."""
import hashlib
import os
import re
from fastapi import Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from .db import SessionLocal
from . import models
from .security import sign, unsign
from .passwords import pw_hash as _pw_hash
from urllib.parse import quote
from .errors import best_effort, rollback_quietly




templates = Jinja2Templates(directory='app/templates')


# Track updates the server deliberately ignores are logged once per (game, reason, key), so a
# disputed bingo ("that song did play!") can be checked against `docker logs bingo-dev`.
_IGNORED_LOGGED = set()


def _log_ignored_once(code: str, reason: str, key: str, msg: str) -> None:
    k = (code, reason, key)
    if k in _IGNORED_LOGGED:
        return
    _IGNORED_LOGGED.add(k)
    print(f"TRACK_UPDATE_IGNORED game={code} reason={reason} {msg}", flush=True)


def _claim_reason(detail: str) -> str:
    """Plain-English reason for a claim's auto-check result (shown to the host), from BingoClaim.detail."""
    d = (detail or "").strip()
    if d.startswith("Bingo line not yet played"):
        m = re.search(r"missing=(\[.*\])\s+mk=", d)
        try:
            import ast
            songs = [str(s) for s in ast.literal_eval(m.group(1))] if m else []
        except Exception:
            songs = []
        return ("Not played yet: " + ", ".join(songs)) if songs else "Some songs in the line haven't been played yet."
    if d.startswith("No complete line found"):
        return "No complete row, column or diagonal is marked."
    if d.startswith("No complete pattern found"):
        return "The squares for this round's win pattern aren't all marked."
    if d.startswith("Bingo validation error"):
        return "The automatic check failed; please check the card yourself."
    return ""


templates.env.filters["claim_reason"] = _claim_reason


def _current_round(g) -> int:
    """Return the current hosted bingo round number (continue_seq) as int."""
    try:
        return int(getattr(g, 'continue_seq', 0) or 0)
    except Exception:
        return 0


def __host_err_redirect(msg: str):
    """Redirect to /host with a short-lived flash cookie so the URL stays clean."""
    try:
        resp = RedirectResponse(url='/host', status_code=302)
        resp.set_cookie('host_flash', quote((msg or '').strip()), path='/', max_age=30)
        return resp
    except Exception:
        return RedirectResponse(url='/host', status_code=302)


def session_stamp(u) -> str:
    """Changes whenever the account's password changes, so sessions made before a password change stop working."""
    return hashlib.sha256((getattr(u, 'password_hash', '') or '').encode()).hexdigest()[:12]


def host_session_value(u) -> str:
    return sign({'host': True, 'uid': int(u.id), 'pv': session_stamp(u)})


def _host_user_from_session(request: Request, db: Session):
    cookie = request.cookies.get('host_session', '')
    data = unsign(cookie) if cookie else None
    if not (data and data.get('host') is True and data.get('uid')):
        return None
    try:
        uid = int(data.get('uid'))
    except Exception:
        return None
    try:
        u = db.query(models.HostUser).filter(models.HostUser.id == uid).first()
    except Exception:
        return None
    # A cookie made before the last password change is no longer good (cookies from before this check have no stamp:
    # they stay valid until they expire, 7 days at most)
    if u is not None and data.get('pv') is not None and data.get('pv') != session_stamp(u):
        return None
    return u


def _require_admin(request: Request, db: Session):
    u = _host_user_from_session(request, db)
    if not u:
        return RedirectResponse(url='/login?next=/play', status_code=302)
    if not getattr(u, "is_admin", False):
        return HTMLResponse("Forbidden", status_code=403)
    return None


def _bootstrap_admin_user(db: Session):
    """Unattended installs: when the database has no users and HOST_ADMIN_PASSWORD is set, create the admin from it.
    Without it nobody is created here: the first visitor gets the setup screen instead (see setup_flow.py)."""
    try:
        existing = db.query(models.HostUser).count()
    except Exception:
        existing = 0
    if existing and existing > 0:
        return
    admin_user = (os.environ.get('HOST_ADMIN_USER') or 'admin').strip()
    admin_pass = (os.environ.get('HOST_ADMIN_PASSWORD') or '').strip()   # optional; only read when the database has no users
    if not admin_pass:
        return
    try:
        db.add(models.HostUser(username=admin_user, password_hash=_pw_hash(admin_pass), is_admin=True))
        db.commit()
    except Exception:
        rollback_quietly(db)


def host_authed(request: Request) -> bool:
    # Valid signature alone is not enough: the user must still exist (deleted users keep old cookies).
    db = SessionLocal()
    try:
        return _host_user_from_session(request, db) is not None
    finally:
        db.close()


# While a host still has a temporary password (see HostUser.must_change_password) only these pages work
_ALLOWED_WHILE_CHANGING_PASSWORD = ('/host/account', '/host/account/password', '/host/logout', '/host/whoami')
MUST_CHANGE_PASSWORD_MSG = 'You are using a temporary password. Choose your own password below to continue.'


def require_host(request: Request, next_path: str = "/host"):
    db = SessionLocal()
    try:
        u = _host_user_from_session(request, db)   # the user must still exist (deleted users keep old cookies)
        if u is None:
            return RedirectResponse(url=f"/login?next={next_path}", status_code=302)
        if getattr(u, 'must_change_password', False) and request.url.path.rstrip('/') not in _ALLOWED_WHILE_CHANGING_PASSWORD:
            return RedirectResponse(url='/host/account?error=' + quote(MUST_CHANGE_PASSWORD_MSG), status_code=302)
    finally:
        db.close()
    return None


def get_host_state_cookie(request: Request) -> dict:
    cookie = request.cookies.get('host_state', '')
    data = unsign(cookie, max_age=600) if cookie else None  # OAuth round-trip must finish within 10 min
    return data or {}


def set_cookie(request: Request, resp, key: str, value: str, days: int = 7):
    # Decide Secure cookie based on actual scheme (supports reverse proxies)
    try:
        proto = (request.headers.get('x-forwarded-proto') or request.url.scheme or '').lower()
    except Exception:
        proto = ''
    secure = (proto == 'https')

    resp.set_cookie(
        key=key,
        value=value,
        httponly=True,
        secure=secure,
        samesite='lax',
        max_age=days * 86400,
        path='/',
    )


def clear_cookie(resp, key: str):
    resp.delete_cookie(key, path='/')


def _upper_code(code: str) -> str:
    # Game codes are letters and digits only (Game.code is String(8)); anything else is dropped.
    return re.sub(r"[^A-Z0-9]", "", (code or "").upper())[:8]


def _player_cookie_name(code: str) -> str:
    return f"bingo_player_{_upper_code(code)}"


def _player_from_cookie(request: Request, db, g):
    """The Player this browser already joined game g as (via its per-game cookie), or None."""
    token = (request.cookies.get(_player_cookie_name(g.code)) or "").strip()
    if not token:
        return None
    return db.query(models.Player).filter(models.Player.game_id == g.id, models.Player.token == token).first()


def _norm_code(code: str) -> str:
    # Normalize game codes for routing and DB lookups (canonical uppercase, letters and digits only, max 8).
    return re.sub(r"[^A-Z0-9]", "", (code or "").upper())[:8]


def _coerce_int_host_user_id(owner_key: str | None):
    """Best-effort: derive host user id from Game.owner_key.
    Supports: '123', 'host:123', 'host_user_id:123'. Returns int|None.
    """
    try:
        ok = (owner_key or "").strip()
    except Exception:
        ok = ""
    if not ok:
        return None
    with best_effort():
        if ok.isdigit():
            return int(ok)
    for pref in ("host:", "host_user_id:", "uid:", "user:"):
        with best_effort():
            if ok.startswith(pref):
                tail = ok[len(pref):].strip()
                if tail.isdigit():
                    return int(tail)
    with best_effort():
        m = re.search(r"(\d+)", ok)
        if m:
            return int(m.group(1))
    return None


def _host_user_id_from_game(g):
    """Return host_user_id int for a Game, or None if unknown."""
    try:
        ok = getattr(g, "owner_key", None)
    except Exception:
        ok = None
    return _coerce_int_host_user_id(ok)


def _owner_key_for_user(u) -> str:
    try:
        uid = int(getattr(u, "id", 0) or 0)
    except Exception:
        uid = 0
    return f"host:{uid}" if uid else "host:0"


def _owned_game(request: Request, db: Session, code: str):
    """Return the Game with this code only if it belongs to the logged-in host, else None."""
    u = _host_user_from_session(request, db)
    if not u:
        return None
    return (db.query(models.Game)
              .filter(models.Game.code == _upper_code(_norm_code(code)),
                      models.Game.owner_key == _owner_key_for_user(u))
              .first())


def _back_to(next_path: str, fallback: str) -> str:
    n = (next_path or '').strip()
    return n if (n.startswith('/') and not n.startswith('//') and '\\' not in n) else fallback


def _host_uid(request, db):
    u = _host_user_from_session(request, db)
    return int(u.id) if u else None


def _game_host_uid(db, g):
    try:
        return _host_user_id_from_game(g)
    except Exception:
        return None


def on_device(path: str, device_id: str) -> str:
    """Pause/Next aimed at the game's own device, not whichever device Spotify last called active (that could be
    a Play Alone player on the same account)."""
    d = (device_id or '').strip()
    return f"{path}?device_id={quote(d)}" if d else path
