from datetime import datetime, timedelta
import requests
from sqlalchemy.orm import Session
from .models import HostSpotifyToken
from .errors import best_effort, log_swallowed, rollback_quietly

# This file intentionally contains ONE set of spotify helper functions.
# Tokens are strictly per-host via host_user_id; host_user_id=None never resolves a token.
#
# IMPORTANT:
#   Do not re-add duplicate defs later in this file; Python will override earlier defs.

from . import settings   # the Spotify developer app comes from the environment or from the app's saved settings

SPOTIFY_AUTH_URL = 'https://accounts.spotify.com/authorize'
SPOTIFY_TOKEN_URL = 'https://accounts.spotify.com/api/token'
SPOTIFY_API_BASE = 'https://api.spotify.com/v1'

SCOPES = 'streaming user-read-email user-read-private user-read-playback-state user-modify-playback-state user-read-currently-playing playlist-read-private playlist-read-collaborative playlist-modify-private playlist-modify-public'


def spotify_auth_url(state: str) -> str:
    params = {
        'client_id': settings.spotify_client_id(),
        'response_type': 'code',
        'redirect_uri': settings.spotify_redirect_uri(),
        'scope': SCOPES,
        'state': state,
        'show_dialog': 'true',
    }
    return requests.Request('GET', SPOTIFY_AUTH_URL, params=params).prepare().url


def exchange_code_for_token(code: str) -> dict:
    data = {
        'grant_type': 'authorization_code',
        'code': code,
        'redirect_uri': settings.spotify_redirect_uri(),
        'client_id': settings.spotify_client_id(),
        'client_secret': settings.spotify_client_secret(),
    }
    r = requests.post(SPOTIFY_TOKEN_URL, data=data, timeout=20)
    r.raise_for_status()
    if r.status_code == 204 or not (r.text or '').strip():
        return {}
    return r.json()



# Validate access tokens proactively so revoked connections are detected immediately.
# We keep a tiny in-process cache to avoid calling Spotify too often per page load.
_SPOTIFY_TOKEN_VALIDATE_CACHE = {}  # key=(host_user_id, access_token) -> (ok:bool, ts:float)
_SPOTIFY_TOKEN_VALIDATE_TTL_SECONDS = 30

def _spotify_access_token_is_valid(access_token: str, host_user_id: int | None = None) -> bool:
    """Return True if token is still accepted by Spotify (quick /v1/me check).

    If the host revoked access, Spotify will respond 401/403.
    We cache results briefly to avoid excessive calls."""
    try:
        import time
        import requests
        tok = (access_token or '').strip()
        if not tok:
            return False
        key = (int(host_user_id or 0) or None, tok)
        now = time.time()
        hit = _SPOTIFY_TOKEN_VALIDATE_CACHE.get(key)
        if hit and isinstance(hit, tuple) and len(hit) == 2:
            ok, ts = hit
            with best_effort():
                if (now - float(ts)) < float(_SPOTIFY_TOKEN_VALIDATE_TTL_SECONDS):
                    return bool(ok)
        r = requests.get(
            'https://api.spotify.com/v1/me',
            headers={'Authorization': f'Bearer {tok}'},
            timeout=10,
        )
        ok = (r.status_code == 200)
        # Explicitly treat 401/403 as revoked/invalid
        if r.status_code in (401, 403):
            ok = False
        _SPOTIFY_TOKEN_VALIDATE_CACHE[key] = (ok, now)
        return bool(ok)
    except Exception as e:
        # If Spotify is down or network hiccups, don't purge; treat as 'valid' to avoid false disconnects.
        log_swallowed(e)
        return True

def refresh_access_token(refresh_token: str) -> dict:
    data = {
        'grant_type': 'refresh_token',
        'refresh_token': refresh_token,
        'client_id': settings.spotify_client_id(),
        'client_secret': settings.spotify_client_secret(),
    }
    r = requests.post(SPOTIFY_TOKEN_URL, data=data, timeout=20)
    r.raise_for_status()
    if r.status_code == 204 or not (r.text or '').strip():
        return {}
    return r.json()


def _token_row_for_host(db: Session, host_user_id: int | None):
    # Return token row for the given host_user_id.
    # No host_user_id => no token. (The old "first row" fallback handed out another host's token.)
    if not host_user_id:
        return None
    row = (
        db.query(HostSpotifyToken)
        .filter(HostSpotifyToken.host_user_id == host_user_id)
        .order_by(HostSpotifyToken.id.asc())
        .first()
    )
    return row


def save_host_token(db: Session, token_json: dict, host_user_id: int | None = None):
    # Persist Spotify token JSON for a given host_user_id.
    if not host_user_id:
        raise RuntimeError('host_user_id is required to save a Spotify token')
    access = (token_json.get('access_token') or '').strip()
    refresh = token_json.get('refresh_token')
    if not access:
        raise RuntimeError('No access_token in token_json')

    expires_in = int(token_json.get('expires_in', 3600))
    expires_at = datetime.utcnow() + timedelta(seconds=max(60, expires_in - 30))

    row = _token_row_for_host(db, host_user_id)
    if row is None:
        if not refresh:
            raise RuntimeError('No refresh_token returned on initial auth')
        row = HostSpotifyToken(access_token=access, refresh_token=refresh, expires_at=expires_at)
        if host_user_id:
            row.host_user_id = host_user_id
        db.add(row)
    else:
        if host_user_id and getattr(row, "host_user_id", None) != host_user_id:
            row.host_user_id = host_user_id
        row.access_token = access
        if refresh:
            row.refresh_token = refresh
        row.expires_at = expires_at

    db.commit()


def get_valid_access_token(db: Session, host_user_id: int | None = None) -> str | None:
    row = _token_row_for_host(db, host_user_id)
    if row is None:
        return None

    # If we have an unexpired access_token, validate it quickly to detect revocation immediately.
    # If revoked (401/403), purge the stored row so UI shows 'not connected'.
    with best_effort():   # if validation blows up, fall through to the refresh path
        if datetime.utcnow() < row.expires_at:
            try:
                ok = _spotify_access_token_is_valid(row.access_token, host_user_id=host_user_id)
            except Exception:
                ok = True
            if ok:
                return row.access_token
            # revoked/invalid token => delete row
            try:
                db.delete(row)
                db.commit()
            except Exception:
                rollback_quietly(db)
            return None

    # Expired token => attempt refresh
    try:
        token_json = refresh_access_token(row.refresh_token)
    except Exception as e:
        # If the user revoked access, Spotify returns a 400 with error=invalid_grant on refresh.
        # In that case, purge the stored token row so the app shows 'not connected'.
        with best_effort():
            import requests
            if isinstance(e, requests.HTTPError) and getattr(e, 'response', None) is not None:
                resp = e.response
                if resp is not None and getattr(resp, 'status_code', None) == 400:
                    err = None
                    try:
                        j = resp.json()
                        err = (j.get('error') if isinstance(j, dict) else None) or ((j.get('error_description') if isinstance(j, dict) else None))
                    except Exception:
                        err = (getattr(resp, 'text', '') or '')
                    if err and 'invalid_grant' in str(err):
                        try:
                            db.delete(row)
                            db.commit()
                        except Exception:
                            rollback_quietly(db)
                        return None
        # Any other failure (Spotify down, no network, wrong client details): keep the saved login, report "not connected"
        # for now and say why in the log. Pages ask this question on every load and must not crash on it.
        log_swallowed(e)
        return None

    token_json['refresh_token'] = token_json.get('refresh_token') or row.refresh_token
    save_host_token(db, token_json, host_user_id=host_user_id)

    row2 = _token_row_for_host(db, host_user_id)
    return row2.access_token if row2 else None

def api_get(db: Session, path: str, params: dict | None = None, host_user_id: int | None = None) -> dict:
    access = get_valid_access_token(db, host_user_id=host_user_id)
    if not access:
        raise RuntimeError('Host is not connected to Spotify yet')
    url = SPOTIFY_API_BASE + path
    r = requests.get(url, headers={'Authorization': f'Bearer {access}'}, params=params or {}, timeout=20)
    if r.status_code == 204:
        return {}
    r.raise_for_status()
    return r.json()


def api_put(db: Session, path: str, json: dict | None = None, params: dict | None = None, host_user_id: int | None = None) -> None:
    access = get_valid_access_token(db, host_user_id=host_user_id)
    if not access:
        raise RuntimeError('Host is not connected to Spotify yet')
    url = SPOTIFY_API_BASE + path
    r = requests.put(url, headers={'Authorization': f'Bearer {access}'}, json=json, params=params or {}, timeout=20)
    if r.status_code not in (200, 204):
        r.raise_for_status()


def api_post(db: Session, path: str, json: dict | None = None, params: dict | None = None, host_user_id: int | None = None) -> dict | None:
    access = get_valid_access_token(db, host_user_id=host_user_id)
    if not access:
        raise RuntimeError('Host is not connected to Spotify yet')
    url = SPOTIFY_API_BASE + path
    r = requests.post(url, headers={'Authorization': f'Bearer {access}'}, json=json, params=params or {}, timeout=20)
    if r.status_code == 204:
        return None
    r.raise_for_status()
    return r.json()
