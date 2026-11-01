"""Host: saved playlists page and the "clean copy" actions."""
import threading
import time
import uuid
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy.orm import Session
from ..db import get_db
from .. import models, spotify
from ..security import unsign
from ..cards import _PLAYLIST_TRACKS_CACHE
from ..common import _host_user_from_session, require_host
from ..playlists import SPOTIFY_MADE_PLAYLIST_ERROR, _CLEAN_JOBS, _CLEAN_JOBS_LOCK, _host_playlists_page, _own_playlist_or_error, _parse_playlist_ref, _playlist_error_text, _playlist_explicit_songs, _refresh_explicit, _run_clean_copy_job, _spotify_made_error, _visible_playlist

router = APIRouter()


@router.get('/host/playlist', response_class=HTMLResponse)
def host_playlist_page(request: Request, db: Session = Depends(get_db)):
    r = require_host(request)
    if r:
        return r
    u = _host_user_from_session(request, db)
    uid = None
    try:
        uid = int(u.id) if u else None
    except Exception:
        uid = None

    # Fallback: if DB lookup fails but host_session cookie is present/valid,
    # still bind the token to the logged-in host uid.
    if uid is None:
        try:
            c = (request.cookies.get('host_session', '') or '').strip()
            d = unsign(c) if c else None
            if d and d.get('host') is True and d.get('uid'):
                uid = int(d.get('uid'))
        except Exception:
            uid = None

    return _host_playlists_page(request, db, u)


@router.post('/host/playlist/save')
def host_playlist_save(request: Request, db: Session = Depends(get_db), name: str = Form(...),
                       playlist_id_or_url: str = Form(...), is_public: str = Form('')):
    r = require_host(request)
    if r:
        return r
    u = _host_user_from_session(request, db)
    uid = int(u.id) if u else None
    if not (uid and spotify.get_valid_access_token(db, host_user_id=uid)):
        return RedirectResponse(url='/host/spotify/connect', status_code=302)

    spotify_playlist_id = _parse_playlist_ref(playlist_id_or_url)
    nm = (name or '').strip() or 'Saved Playlist'
    if not spotify_playlist_id:
        return _host_playlists_page(request, db, u, "That doesn't look like a Spotify playlist link.", 400)
    if _spotify_made_error(spotify_playlist_id):
        return _host_playlists_page(request, db, u, SPOTIFY_MADE_PLAYLIST_ERROR, 400)
    try:
        _ = spotify.api_get(db, f'/playlists/{spotify_playlist_id}', params={'market': 'US'}, host_user_id=uid)
    except Exception as e:
        return _host_playlists_page(request, db, u, _playlist_error_text(e), 400)

    # Saving a playlist you already saved updates its name and visibility; other hosts' saves are separate
    public = bool(is_public)
    existing = (db.query(models.SavedPlaylist)
                  .filter(models.SavedPlaylist.created_by_user_id == uid,
                          models.SavedPlaylist.spotify_playlist_id == spotify_playlist_id).first())
    if existing:
        existing.name = nm
        existing.is_public = public
    else:
        db.add(models.SavedPlaylist(name=nm, spotify_playlist_id=spotify_playlist_id, created_by_user_id=uid, is_public=public))
    db.commit()
    saved = (existing or db.query(models.SavedPlaylist).filter(models.SavedPlaylist.created_by_user_id == uid,
             models.SavedPlaylist.spotify_playlist_id == spotify_playlist_id).first())
    if saved:
        _refresh_explicit(db, saved, uid)
    return RedirectResponse(url='/host/playlist', status_code=302)


@router.get('/host/playlist/explicit')
def host_playlist_explicit(request: Request, db: Session = Depends(get_db)):
    """Explicit songs in a saved playlist: ?id=<saved playlist id>."""
    r = require_host(request)
    if r:
        return JSONResponse({'ok': False, 'error': 'login required'}, status_code=401)
    u = _host_user_from_session(request, db)
    uid = int(u.id) if u else None
    pl = _visible_playlist(db, uid, request.query_params.get('id') or '')
    pid = pl.spotify_playlist_id if pl else ''
    if not pid:
        return JSONResponse({'ok': False, 'error': 'playlist not found'}, status_code=404)
    try:
        titles, total = _playlist_explicit_songs(db, pid, uid)
    except Exception:
        return JSONResponse({'ok': False, 'error': "Couldn't read the playlist"}, status_code=502)
    return JSONResponse({'ok': True, 'explicit': len(titles), 'total': total, 'titles': sorted(titles, key=str.lower)[:200]})


@router.post('/host/playlist/clean_copy')
def host_playlist_clean_copy(request: Request, db: Session = Depends(get_db), playlist_id: int = Form(...)):
    """Start making a copy of a saved playlist in the host's own Spotify with the explicit songs swapped for clean
    versions (or left out). It runs in the background; Manage Playlists shows its progress. The original is untouched."""
    r = require_host(request)
    if r:
        return r
    u = _host_user_from_session(request, db)
    uid = int(u.id) if u else None
    if not (uid and spotify.get_valid_access_token(db, host_user_id=uid)):
        return RedirectResponse(url='/host/spotify/connect?next=/host/playlist', status_code=302)
    pl = _visible_playlist(db, uid, playlist_id)
    if not pl:
        return _host_playlists_page(request, db, u, 'Saved playlist not found.', 404)
    with _CLEAN_JOBS_LOCK:
        mine = [j for j in _CLEAN_JOBS.values() if j['uid'] == uid and j['state'] == 'running']
        if any(j['playlist_id'] == pl.id for j in mine):
            return RedirectResponse(url='/host/playlist', status_code=302)     # already being made
        if len(mine) >= 3:
            full = True
        else:
            full = False
            job_id = uuid.uuid4().hex[:12]
            _CLEAN_JOBS[job_id] = {'id': job_id, 'uid': uid, 'playlist_id': pl.id, 'playlist_name': pl.name, 'state': 'running',
                                   'phase': 'Starting', 'done': 0, 'total': 0, 'started': time.time()}
    if full:
        return _host_playlists_page(request, db, u, 'Three clean copies are already being made. Wait for one to finish, then start another.', 429)
    threading.Thread(target=_run_clean_copy_job, args=(job_id, uid, pl.id), daemon=True).start()
    return RedirectResponse(url='/host/playlist', status_code=302)


@router.get('/host/playlist/clean_jobs')
def host_playlist_clean_jobs(request: Request, db: Session = Depends(get_db)):
    """This host's clean copies that are running or finished (finished ones stay until dismissed, for 30 minutes)."""
    r = require_host(request)
    if r:
        return JSONResponse({'error': 'login required'}, status_code=401)
    u = _host_user_from_session(request, db)
    uid = int(u.id) if u else None
    now = time.time()
    with _CLEAN_JOBS_LOCK:
        for k in [k for k, j in _CLEAN_JOBS.items() if j.get('finished') and now - j['finished'] > 1800]:
            _CLEAN_JOBS.pop(k, None)
        jobs = [dict(j) for j in _CLEAN_JOBS.values() if j['uid'] == uid]
    for j in jobs:
        j.pop('uid', None)
    return JSONResponse({'jobs': sorted(jobs, key=lambda j: j['started'])})


@router.post('/host/playlist/clean_jobs/dismiss')
def host_playlist_clean_jobs_dismiss(request: Request, db: Session = Depends(get_db), job_id: str = Form(...)):
    r = require_host(request)
    if r:
        return JSONResponse({'error': 'login required'}, status_code=401)
    u = _host_user_from_session(request, db)
    uid = int(u.id) if u else None
    with _CLEAN_JOBS_LOCK:
        j = _CLEAN_JOBS.get(job_id)
        if j and j['uid'] == uid and j['state'] != 'running':
            _CLEAN_JOBS.pop(job_id, None)
    return JSONResponse({'ok': True})


@router.post('/host/playlist/explicit_refresh')
def host_playlist_explicit_refresh(request: Request, db: Session = Depends(get_db), playlist_id: int = Form(...)):
    r = require_host(request)
    if r:
        return r
    u = _host_user_from_session(request, db)
    uid = int(u.id) if u else None
    pl = _visible_playlist(db, uid, playlist_id)
    if pl:
        _PLAYLIST_TRACKS_CACHE.clear()   # re-check against the playlist as it is now
        err = _refresh_explicit(db, pl, uid)
        if err:
            return _host_playlists_page(request, db, u, f"{pl.name}: {err}", 400)
    return RedirectResponse(url='/host/playlist', status_code=302)


@router.post('/host/playlist/rename')
def host_playlist_rename(request: Request, db: Session = Depends(get_db), playlist_id: int = Form(...), name: str = Form('')):
    # Only the host who added a playlist can rename it (same rule as delete and public/private)
    r = require_host(request)
    if r:
        return r
    u, pl, err = _own_playlist_or_error(request, db, playlist_id, 'rename')
    if err:
        return err
    nm = (name or '').strip()[:200]
    if not nm:
        return _host_playlists_page(request, db, u, 'A playlist needs a name.', 400)
    pl.name = nm
    db.commit()
    return RedirectResponse(url='/host/playlist', status_code=302)


@router.post('/host/playlist/delete')
def host_playlist_delete(request: Request, db: Session = Depends(get_db), playlist_id: int = Form(...)):
    # Only the host who added a playlist can remove it (the old version of this route crashed for everyone)
    r = require_host(request)
    if r:
        return r
    u, pl, err = _own_playlist_or_error(request, db, playlist_id, 'remove')
    if err:
        return err
    db.delete(pl)
    db.commit()
    return RedirectResponse(url='/host/playlist', status_code=302)


@router.post('/host/playlist/visibility')
def host_playlist_visibility(request: Request, db: Session = Depends(get_db), playlist_id: int = Form(...), is_public: str = Form('')):
    # Public: every host can use it. Private: only you. Only the host who added it can switch.
    r = require_host(request)
    if r:
        return r
    u, pl, err = _own_playlist_or_error(request, db, playlist_id, 'change')
    if err:
        return err
    pl.is_public = bool(is_public)
    db.commit()
    return RedirectResponse(url='/host/playlist', status_code=302)
