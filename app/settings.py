"""App settings that can come from the environment or be saved in the database (setup screen and Admin page).
A value set in the environment always wins, so existing installs behave exactly as before."""
import os
from urllib.parse import urlparse

from .db import SessionLocal
from . import models

KEYS = ('PUBLIC_BASE_URL', 'SPOTIFY_CLIENT_ID', 'SPOTIFY_CLIENT_SECRET', 'SPOTIFY_REDIRECT_URI')
_cache = None   # key -> saved value; one worker process, refreshed whenever a value is saved here


def _load() -> dict:
    global _cache
    if _cache is None:
        db = SessionLocal()
        try:
            _cache = {r.key: (r.value or '') for r in db.query(models.AppSetting).all()}
        except Exception:
            return {}   # the table may not exist yet while the app is starting; try again next time
        finally:
            db.close()
    return _cache


def from_env(key: str) -> str:
    return (os.environ.get(key) or '').strip()


def get(key: str, default: str = '') -> str:
    return from_env(key) or (_load().get(key) or '').strip() or default


def source(key: str) -> str:
    """'env' (set in the environment, read only here), 'saved' (set in the app) or '' (not set)."""
    if from_env(key):
        return 'env'
    return 'saved' if (_load().get(key) or '').strip() else ''


def save(db, values: dict) -> None:
    """Save settings (only the known keys). An empty value removes the saved one."""
    global _cache
    for k, v in values.items():
        if k not in KEYS:
            continue
        row = db.query(models.AppSetting).filter(models.AppSetting.key == k).first()
        v = (v or '').strip()
        if not v:
            if row:
                db.delete(row)
        elif row:
            row.value = v
        else:
            db.add(models.AppSetting(key=k, value=v))
    db.commit()
    _cache = None


def public_base() -> str:
    return get('PUBLIC_BASE_URL', 'http://localhost:5000').rstrip('/')


def public_host() -> str:
    return urlparse(public_base()).netloc.lower()


def spotify_client_id() -> str:
    return get('SPOTIFY_CLIENT_ID')


def spotify_client_secret() -> str:
    return get('SPOTIFY_CLIENT_SECRET')


def spotify_redirect_uri() -> str:
    return get('SPOTIFY_REDIRECT_URI') or public_base() + '/auth/spotify/callback'
