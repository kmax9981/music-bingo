"""Host: connecting and disconnecting Spotify, token and device transfer endpoints."""
import secrets
import hmac
from fastapi import APIRouter, Depends, Request
from starlette.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.orm import Session
from ..db import get_db
from .. import models, spotify, settings
from ..security import sign
from ..common import __host_err_redirect, _host_user_from_session, clear_cookie, get_host_state_cookie, require_host, set_cookie
from ..errors import best_effort, log_swallowed, rollback_quietly

router = APIRouter()


@router.post('/host/spotify/disconnect')
def host_spotify_disconnect(request: Request, db: Session = Depends(get_db)):
    r = require_host(request)
    if r:
        return r
    u = _host_user_from_session(request, db)
    uid = int(u.id) if u else None

    # Purge stored token row for this host user.
    if uid:
        try:
            db.query(models.HostSpotifyToken).filter(models.HostSpotifyToken.host_user_id == uid).delete(synchronize_session=False)
            db.commit()
        except Exception:
            rollback_quietly(db)

    return RedirectResponse(url='/host', status_code=302)


@router.get('/host/spotify/connect')
def host_spotify_connect(request: Request):
    r = require_host(request)
    if r:
        return r
    # Optional redirect-back for UX (e.g., Play Alone page)
    # Only allow relative paths to prevent open-redirect.
    try:
        nxt = (request.query_params.get('next') or '').strip()
    except Exception:
        nxt = ''
    if not (nxt.startswith('/') and '://' not in nxt and '\\' not in nxt):
        nxt = ''

    if not (settings.spotify_client_id() and settings.spotify_client_secret()):
        # Without these Spotify would only answer "client_id: Not present"
        return _spotify_connect_failed("Spotify isn't set up yet: the Spotify client ID and secret are missing. "
                                       "An admin can add them on the Admin page (menu, top right) under App settings.")

    state = secrets.token_urlsafe(24)
    resp = RedirectResponse(url=spotify.spotify_auth_url(state), status_code=302)
    payload = {'state': state}
    if nxt:
        payload['next'] = nxt
    set_cookie(request, resp, 'host_state', sign(payload))
    return resp


# Shown on the Host Dashboard when Spotify turns a host away (no more silent bounce to the login page)
_SPOTIFY_ASK_OWNER = "If this keeps happening, ask whoever runs this app to add your Spotify email to its Spotify developer app."


_SPOTIFY_NOT_REGISTERED = ("Spotify didn't connect: Spotify won't let this Spotify account use the app yet. "
                           "Ask whoever runs this app to add your Spotify email to its Spotify developer app.")


def _spotify_connect_failed(msg: str):
    resp = __host_err_redirect(msg)
    clear_cookie(resp, 'host_state')
    return resp


@router.get('/auth/spotify/callback')
def spotify_callback(request: Request, db: Session = Depends(get_db), code: str = '', state: str = '', error: str = ''):
    r = require_host(request)
    if r:
        return r

    u = _host_user_from_session(request, db)
    uid = int(u.id) if u else None

    # Validate OAuth state (stored in signed host_state cookie). Missing or mismatched state is
    # rejected: otherwise a crafted callback link could attach someone else's Spotify to this host.
    hs = get_host_state_cookie(request) or {}
    expected = (hs.get('state') or '').strip()
    if not expected or not state or not hmac.compare_digest(state, expected):
        print(f"SPOTIFY_CALLBACK_STATE_REJECTED uid={uid} has_cookie={bool(expected)} has_state={bool(state)}")
        return _spotify_connect_failed("Spotify didn't connect: the sign-in expired or came from another tab. "
                                       "Click Connect Spotify to try again.")

    # Spotify sends ?error=... instead of a code when the host cancels or Spotify refuses
    if (error or '').strip() or not (code or '').strip():
        why = "access was denied" if (error or '').strip() == 'access_denied' else f"Spotify said \"{(error or 'no sign-in code').strip()}\""
        print(f"SPOTIFY_CB_REFUSED user={getattr(u,'username',None)} error={error!r}")
        return _spotify_connect_failed(f"Spotify didn't connect: {why}. {_SPOTIFY_ASK_OWNER}")

    try:
        tok = spotify.exchange_code_for_token(code)
        spotify.save_host_token(db, tok, host_user_id=uid)
    except Exception as e:
        print(f"SPOTIFY_CB_FAILED user={getattr(u,'username',None)} {e!r}")
        return _spotify_connect_failed(f"Spotify didn't connect: the sign-in couldn't be completed. {_SPOTIFY_ASK_OWNER}")

    # An app in Spotify's Development Mode signs in accounts that aren't on its user list, then refuses their
    # requests (403). Check once now, so the host hears why instead of hitting errors later.
    try:
        spotify.api_get(db, '/me', host_user_id=uid)
    except Exception as e:
        if getattr(getattr(e, 'response', None), 'status_code', None) == 403:
            print(f"SPOTIFY_CB_NOT_REGISTERED user={getattr(u,'username',None)}")
            try:
                db.query(models.HostSpotifyToken).filter(models.HostSpotifyToken.host_user_id == uid).delete(synchronize_session=False)
                db.commit()
            except Exception:
                db.rollback()
            return _spotify_connect_failed(_SPOTIFY_NOT_REGISTERED)

    # Redirect back to the originating page if provided (e.g., /play)
    next_url = '/host'
    with best_effort():
        hs = get_host_state_cookie(request) or {}
        nx = (hs.get('next') or '').strip()
        if nx.startswith('/') and '://' not in nx and '\\' not in nx:
            next_url = nx

    resp = RedirectResponse(url=next_url, status_code=302)
    clear_cookie(resp, 'host_state')
    return resp


@router.get('/api/spotify/token')
def api_spotify_token(request: Request, db: Session = Depends(get_db)):
    r = require_host(request)
    if r:
        return JSONResponse({'error': 'not authed'}, status_code=401)
    try:
        u = _host_user_from_session(request, db)
        host_user_id = int(u.id) if u else None

        tok = spotify.get_valid_access_token(db, host_user_id=host_user_id)
        if not tok:
            return JSONResponse({'error': 'Host is not connected to Spotify yet'}, status_code=400)
        return JSONResponse({'access_token': tok})
    except Exception as e:
        return JSONResponse({'error': str(e)}, status_code=400)


@router.post('/api/spotify/transfer')
async def api_spotify_transfer(request: Request, db: Session = Depends(get_db)):
    r = require_host(request)
    if r:
        return r


    # Resolve host_user_id from session (required for host token)
    u = None
    try:
        u = _host_user_from_session(request, db)
    except Exception:
        u = None
    uid = int(getattr(u, "id", 0) or 0) or None
    host_user_id = uid
    try:
        payload = await request.json()
    except Exception:
        payload = {}

    device_id = (payload.get('device_id') or '').strip()
    play = bool(payload.get('play', False))

    # If device_id wasn't provided by the UI yet, pick a sensible default.
    if not device_id:
        try:
            j = await run_in_threadpool(spotify.api_get, db, '/me/player/devices', host_user_id=uid)
            devs = (j.get('devices') or [])
        except Exception as e:
            log_swallowed(e)
            devs = []

        chosen = None
        # Prefer active device first
        for d in devs:
            if d.get('is_active'):
                chosen = d
                break
        # Otherwise prefer the named host player
        if not chosen:
            for d in devs:
                name = (d.get('name') or '').lower()
                if 'bingo host player' in name:
                    chosen = d
                    break
        # Otherwise take first device
        if not chosen and devs:
            chosen = devs[0]

        if chosen:
            device_id = (chosen.get('id') or '').strip()

    if not device_id:
        return JSONResponse({'error': 'device_id required', 'hint': 'Start embedded player first, or open Spotify on a device.'}, status_code=400)
    # PUT https://api.spotify.com/v1/me/player   { "device_ids": [...], "play": false }
    try:
        await run_in_threadpool(spotify.api_put, db, '/me/player', json={'device_ids': [device_id], 'play': play}, host_user_id=host_user_id)
        return JSONResponse({'ok': True, 'device_id': device_id})
    except Exception as e:
        return JSONResponse({'error': str(e)}, status_code=400)
