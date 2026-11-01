"""Saved playlists: parsing links, explicit-song flags and the "clean copy" background job."""
import threading
import time
import sqlalchemy as sa
import re
from datetime import datetime, timedelta
from .db import SessionLocal
from . import models, spotify
from .util import clean_song_title, normalize_key
from urllib.parse import quote
from .cards import _fetch_playlist_tracks, _fetch_playlist_tracks_uncached
from . import settings
from .common import _host_user_from_session, templates
from .errors import best_effort, log_swallowed


_PLAYLIST_ID_RE = re.compile(r'playlist[/:]([A-Za-z0-9]{22})')


_SHORT_LINK_RE = re.compile(r'^https?://(spotify\.link|spotify\.app\.link)/[A-Za-z0-9_-]+', re.I)


def _parse_playlist_ref(raw: str) -> str:
    """Accepts an open.spotify.com link (any locale prefix), a spotify:playlist: URI,
    a spotify.link share link, or a bare ID. Returns the playlist ID, or '' if none found."""
    v = (raw or '').strip()
    if re.fullmatch(r'[A-Za-z0-9]{22}', v):
        return v
    m = _PLAYLIST_ID_RE.search(v)
    if m:
        return m.group(1)
    if _SHORT_LINK_RE.match(v):
        with best_effort():
            import requests
            r = requests.get(v, timeout=6, allow_redirects=True, headers={'User-Agent': 'Mozilla/5.0'})
            m = _PLAYLIST_ID_RE.search(r.url) or _PLAYLIST_ID_RE.search(r.text[:200000])
            if m:
                return m.group(1)
    return ''


# Playlists made by Spotify itself (Today's Top Hits, Daily Mix, "This Is…", Discover Weekly...) all have IDs
# starting with this, and Spotify doesn't let apps read them. Caught up front for a clear message.
_SPOTIFY_MADE_PREFIX = '37i9dQZF1'


_COPY_TIP = ("To use it, open it in Spotify, choose ⋯ → Add to other playlist → New playlist, "
             "then paste the link to your copy.")


SPOTIFY_MADE_PLAYLIST_ERROR = ("That's a playlist made by Spotify, and Spotify doesn't let apps use those. " + _COPY_TIP)


def _spotify_made_error(playlist_id: str):
    """The error text if this is a playlist made by Spotify itself, else None."""
    return SPOTIFY_MADE_PLAYLIST_ERROR if (playlist_id or '').startswith(_SPOTIFY_MADE_PREFIX) else None


def _playlist_error_text(e: Exception) -> str:
    code = getattr(getattr(e, 'response', None), 'status_code', None)
    if code == 404:
        return ("Spotify won't let the app read that playlist. Playlists made by Spotify (like Today's Top Hits, "
                "Daily Mix or \"This Is…\") and other people's private playlists can't be used. " + _COPY_TIP)
    return f'Spotify error while reading the playlist: {e}'


def _visible_playlists(db, uid):
    """Saved playlists this host may use: every public one plus their own private ones."""
    return (db.query(models.SavedPlaylist)
              .filter(sa.or_(models.SavedPlaylist.is_public == sa.true(), models.SavedPlaylist.created_by_user_id == uid))
              .order_by(models.SavedPlaylist.created_at.desc()))


def _playlist_explicit_songs(db, playlist_id, host_uid):
    """(titles of the explicit songs, number of songs) in a playlist, counting each song once."""
    tracks = _fetch_playlist_tracks(db, playlist_id, market="US", limit=100, host_user_id=host_uid)
    titles, seen, total = [], set(), 0
    for row in (tracks or []):
        tr = (row.get('track') or row) if isinstance(row, dict) else {}
        if not isinstance(tr, dict) or tr.get('is_local') or not tr.get('name'):
            continue
        key = tr.get('id') or tr.get('name')
        if key in seen:
            continue
        seen.add(key)
        total += 1
        if tr.get('explicit') is True:
            titles.append(str(tr.get('name')))
    return titles, total


def _refresh_explicit(db, pl, host_uid):
    """Count the explicit songs of a saved playlist and remember it. Returns None on success, or a plain-language
    reason when Spotify can't be read (the old counts stay; the attempt time is kept so it isn't retried at once)."""
    try:
        titles, total = _playlist_explicit_songs(db, pl.spotify_playlist_id, host_uid)
    except Exception as e:
        print(f'EXPLICIT_CHECK_FAILED playlist={pl.id} ({pl.spotify_playlist_id}): {e!r}')
        try:
            pl.explicit_checked_at = datetime.utcnow()
            db.commit()
        except Exception:
            db.rollback()
        if _spotify_status(e) == 404:
            return ("Spotify can't find that playlist any more: it may have been deleted, or its owner made it private. "
                    "If you still have it, save it again from its link; otherwise remove it from this list.")
        if _spotify_status(e) in (401, 403) or 'not connected' in str(e).lower():
            return "Spotify isn't letting the app read it. Reconnect Spotify from the Host Dashboard and try again."
        return "Couldn't read the playlist from Spotify right now. Try again in a moment."
    pl.explicit_count, pl.track_count, pl.explicit_checked_at = len(titles), total, datetime.utcnow()
    db.commit()
    return None


def _fill_missing_explicit(db, playlists, host_uid, limit=4):
    """Check a few saved playlists that have never been counted (existing ones), so old playlists get a count too.
    One that Spotify couldn't read is tried again after an hour, not on every page view."""
    done = 0
    cutoff = datetime.utcnow() - timedelta(hours=1)
    for pl in playlists:
        if done >= limit:
            break
        if pl.track_count is None and host_uid and (pl.explicit_checked_at is None or pl.explicit_checked_at < cutoff):
            _refresh_explicit(db, pl, host_uid)
            done += 1


def _explicit_note(pl):
    """' (12 explicit)' for playlist menus; empty when clean or not checked yet."""
    n = getattr(pl, 'explicit_count', None)
    return f' ({n} explicit)' if n else ''


templates.env.globals['explicit_note'] = _explicit_note


def _visible_playlist(db, uid, playlist_id):
    """One saved playlist, or None if it doesn't exist or is someone else's private playlist."""
    try:
        pid = int(playlist_id)
    except Exception:
        return None
    return _visible_playlists(db, uid).filter(models.SavedPlaylist.id == pid).first()


def _host_playlists_page(request, db, u, error=None, status_code=200, reconnect=False):
    """Manage Playlists: public playlists plus this host's private ones, with who added each."""
    uid = int(getattr(u, 'id', 0) or 0) or None
    playlists = _visible_playlists(db, uid).all()
    _fill_missing_explicit(db, playlists, uid, limit=6)
    owner_ids = {pl.created_by_user_id for pl in playlists if pl.created_by_user_id}
    owners = {hu.id: hu.username for hu in db.query(models.HostUser).filter(models.HostUser.id.in_(owner_ids)).all()} if owner_ids else {}
    return templates.TemplateResponse(request, 'host_playlists.html', {
        'request': request,
        'user': u,
        'uid': uid,
        'public_base': settings.public_base(),
        'playlists': playlists,
        'owners': owners,
        'spotify_connected': bool(uid and spotify.get_valid_access_token(db, host_user_id=uid)),
        'error': error,
        'reconnect': reconnect,
    }, status_code=status_code)


_NOT_THE_SAME_RECORDING = re.compile(r"\b(live|karaoke|instrumental|cover|tribute|acoustic|demo|remix|re-?record(?:ed|ing)?|sped up|slowed|nightcore|8d)\b", re.I)


def _find_clean_version(db, uid, tr):
    """The clean (not explicit) release of an explicit song, or None. Only accepts the same title (version tags
    aside), the same main artist and about the same length, and never a live, karaoke, remix or cover version."""
    name = str(tr.get('name') or '')
    artists = [str(a.get('name') or '') for a in (tr.get('artists') or []) if isinstance(a, dict)]
    main = artists[0].lower() if artists else ''
    if not name or not main:
        return None
    want = normalize_key(clean_song_title(name))
    q = f'track:"{name.replace(chr(34), " ")}" artist:"{artists[0].replace(chr(34), " ")}"'
    try:
        res = spotify.api_get(db, '/search', params={'q': q, 'type': 'track', 'limit': 10, 'market': 'US'}, host_user_id=uid)
    except Exception as e:
        log_swallowed(e)
        return None
    for c in ((res or {}).get('tracks') or {}).get('items') or []:
        if not isinstance(c, dict) or c.get('explicit') is not False or c.get('is_local') or not c.get('uri'):
            continue
        cname = str(c.get('name') or '')
        if normalize_key(clean_song_title(cname)) != want:
            continue
        if _NOT_THE_SAME_RECORDING.search(cname) and not _NOT_THE_SAME_RECORDING.search(name):
            continue
        if main not in [str(a.get('name') or '').lower() for a in (c.get('artists') or []) if isinstance(a, dict)]:
            continue
        d1, d2 = tr.get('duration_ms'), c.get('duration_ms')
        if isinstance(d1, int) and isinstance(d2, int) and abs(d1 - d2) > 15000:
            continue
        return c
    return None


def _spotify_status(exc):
    return getattr(getattr(exc, 'response', None), 'status_code', None)


def _spotify_create_playlist(db, uid, name, description):
    """Create a private playlist in the host's own Spotify account; returns its id. Spotify has changed the
    create endpoint, so try the current one first and fall back to the older per-user one."""
    try:
        made = spotify.api_post(db, '/me/playlists', json={'name': name, 'public': False, 'description': description}, host_user_id=uid)
    except Exception as e:
        if _spotify_status(e) not in (404, 405):
            raise
        me = spotify.api_get(db, '/me', host_user_id=uid)
        made = spotify.api_post(db, f"/users/{quote(str(me.get('id') or ''))}/playlists",
                        json={'name': name, 'public': False, 'description': description}, host_user_id=uid)
    return (made or {}).get('id')


def _spotify_add_tracks(db, uid, playlist_id, uris):
    """Add songs to a playlist, 100 at a time (the older /tracks path first, then the newer /items path)."""
    for i in range(0, len(uris), 100):
        chunk = uris[i:i + 100]
        try:
            spotify.api_post(db, f'/playlists/{playlist_id}/tracks', json={'uris': chunk}, host_user_id=uid)
        except Exception as e:
            if _spotify_status(e) not in (404, 405):
                raise
            spotify.api_post(db, f'/playlists/{playlist_id}/items', json={'uris': chunk}, host_user_id=uid)


_CLEAN_JOBS = {}            # job id -> progress and result of a clean copy running (or finished) in the background


_CLEAN_JOBS_LOCK = threading.Lock()


def _job_update(job_id, **fields):
    with _CLEAN_JOBS_LOCK:
        if job_id in _CLEAN_JOBS:
            _CLEAN_JOBS[job_id].update(fields)


def _find_my_playlist_by_name(db, uid, name):
    """A playlist in the host's own Spotify with exactly this name (any case), or None. Dev and production keep
    separate saved lists but share the host's Spotify, so a copy made from one is only visible here."""
    want = (name or '').strip().lower()
    try:
        me = (spotify.api_get(db, '/me', host_user_id=uid) or {}).get('id')
        offset = 0
        while offset < 1000:
            page = spotify.api_get(db, '/me/playlists', params={'limit': 50, 'offset': offset}, host_user_id=uid) or {}
            items = page.get('items') or []
            for it in items:
                if isinstance(it, dict) and str(it.get('name') or '').strip().lower() == want and (it.get('owner') or {}).get('id') == me:
                    return it
            if not items or not page.get('next'):
                break
            offset += 50
    except Exception as e:
        log_swallowed(e)
        return None
    return None


def _do_clean_copy(db, uid, pl, progress):
    """Make the copy: read the playlist, find clean versions of the explicit songs, create the playlist in the
    host's Spotify and save it. Returns {'ok': True, 'name', 'count', 'swapped', 'left_out'} or {'ok': False, 'error', 'reconnect'}."""
    # Already made (maybe from the other copy of this app)? Use that one instead of making a duplicate.
    progress(phase='Checking your Spotify for an existing copy')
    name = f"{pl.name} (Clean)"[:100]
    found = _find_my_playlist_by_name(db, uid, name)
    if found and found.get('id'):
        already = (db.query(models.SavedPlaylist)
                     .filter(models.SavedPlaylist.created_by_user_id == uid, models.SavedPlaylist.spotify_playlist_id == found['id']).first())
        if not already:
            already = models.SavedPlaylist(name=str(found.get('name') or name)[:200], spotify_playlist_id=found['id'], created_by_user_id=uid, is_public=bool(pl.is_public))
            db.add(already)
            db.commit()
            _refresh_explicit(db, already, uid)
        return {'ok': True, 'reused': True, 'name': already.name, 'count': already.track_count or 0, 'swapped': 0, 'left_out': 0}
    progress(phase='Reading the playlist')
    try:
        tracks = _fetch_playlist_tracks_uncached(db, pl.spotify_playlist_id, 'US', 100, 0, uid)
    except Exception:
        return {'ok': False, 'error': "Couldn't read that playlist from Spotify. Check Spotify is connected and try again."}
    uris, seen, total, explicit_tracks = [], set(), 0, []
    for row in (tracks or []):
        tr = (row.get('track') or row) if isinstance(row, dict) else {}
        if not isinstance(tr, dict) or tr.get('is_local') or not tr.get('name') or not tr.get('uri'):
            continue
        key = tr.get('id') or tr.get('uri')
        if key in seen:
            continue
        seen.add(key)
        total += 1
        if tr.get('explicit') is not True:
            uris.append(str(tr['uri']))
        else:
            explicit_tracks.append(tr)
    # Explicit songs that have a clean release: use that one; the rest are left out
    swapped, have = 0, set(uris)
    todo = explicit_tracks[:80]
    for n, tr in enumerate(todo, 1):
        progress(phase='Looking for clean versions of the explicit songs', done=n - 1, total=len(todo))
        c = _find_clean_version(db, uid, tr)
        if c and str(c['uri']) not in have:
            uris.append(str(c['uri'])); have.add(str(c['uri'])); swapped += 1
    left_out = len(explicit_tracks) - swapped
    if len(uris) < 24:
        return {'ok': False, 'error': f"Only {len(uris)} of the {total} songs in {pl.name} can be used clean ({swapped} swapped for clean versions, {left_out} left out), and a game needs at least 24 different songs, so a clean copy would be too short."}
    try:
        progress(phase='Creating the playlist in your Spotify', done=len(todo), total=len(todo))
        new_id = _spotify_create_playlist(db, uid, name, 'A clean copy made by Music Bingo: the explicit songs are left out.')
        if not new_id:
            raise RuntimeError('Spotify did not return the new playlist')
        progress(phase='Adding the songs')
        _spotify_add_tracks(db, uid, new_id, uris)
    except Exception as e:
        print(f'CLEAN_COPY_FAILED playlist={pl.id}: {e!r} {str(getattr(getattr(e, "response", None), "text", ""))[:300]}')
        if _spotify_status(e) in (401, 403):
            return {'ok': False, 'reconnect': True, 'error': "Spotify hasn't given this app permission to create playlists in your account yet. Reconnect Spotify and approve the extra permission, then try again."}
        return {'ok': False, 'error': "Spotify wouldn't create the copy right now. Try again in a moment."}
    db.add(models.SavedPlaylist(name=name, spotify_playlist_id=new_id, created_by_user_id=uid, is_public=bool(pl.is_public),
                                explicit_count=0, track_count=len(uris), explicit_checked_at=datetime.utcnow()))
    db.commit()
    return {'ok': True, 'name': name, 'count': len(uris), 'swapped': swapped, 'left_out': left_out}


def _run_clean_copy_job(job_id, uid, playlist_pk):
    db = SessionLocal()
    try:
        pl = _visible_playlist(db, uid, playlist_pk)
        res = _do_clean_copy(db, uid, pl, lambda **kw: _job_update(job_id, **kw)) if pl else {'ok': False, 'error': 'Saved playlist not found.'}
    except Exception as e:
        print(f'CLEAN_COPY_JOB_CRASHED {job_id}: {e!r}')
        res = {'ok': False, 'error': 'Something went wrong making the copy. Try again.'}
    finally:
        db.close()
    _job_update(job_id, state='done' if res.get('ok') else 'error', finished=time.time(), **res)


def _own_playlist_or_error(request, db, playlist_id, action):
    """(u, playlist, None) if the logged-in host added this playlist, else (u, None, error page)."""
    u = _host_user_from_session(request, db)
    uid = int(u.id) if u else None
    pl = db.query(models.SavedPlaylist).filter(models.SavedPlaylist.id == playlist_id).first()
    if not pl or not _visible_playlist(db, uid, playlist_id):
        return u, None, _host_playlists_page(request, db, u, 'Saved playlist not found.', 404)
    if pl.created_by_user_id is None or uid is None or int(pl.created_by_user_id) != uid:
        return u, None, _host_playlists_page(request, db, u, f'Only the host who added a playlist can {action} it.', 403)
    return u, pl, None
