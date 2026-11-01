"""Host: music playback (play, pause, next) and the song-played updates that drive the live game."""
import threading
import time
from fastapi import APIRouter, Depends, Request
from starlette.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.orm import Session
from ..db import get_db
from .. import models, spotify
from ..ws import hub
from ..util import clean_title_for_card, normalize_key
from urllib.parse import quote
from ..cards import _bingo_clean_title_display, _bingo_get_playlist_track_ids
from ..common import on_device, _host_user_from_session, _log_ignored_once, _owner_key_for_user, require_host
from ..state import LAST_TRACK_STATE, _PLAY_RESTARTED_AT, _PLAY_RESTART_LOCK
from ..errors import best_effort, log_swallowed

router = APIRouter()


@router.post('/host/game/{code}/spotify/play')
def host_spotify_play(request: Request, code: str, device_id: str = '', db: Session = Depends(get_db)):
    r = require_host(request)
    if r:
        return r

    u = _host_user_from_session(request, db)
    if not u:
        return RedirectResponse(url="/login?next=/host", status_code=302)
    uid = int(getattr(u, 'id', 0) or 0) or None
    owner_key = _owner_key_for_user(u)
    code_u = (code or '').strip().upper()
    g = (db.query(models.Game)
        .filter(models.Game.code == code_u, models.Game.owner_key == owner_key, models.Game.game_type == 'hosted')
        .first())

    if not g:
        return JSONResponse({'error': 'Game not found'}, status_code=404)

    # hosted games only
    if (getattr(g, 'game_type', '') or '').lower() != 'hosted':
        return JSONResponse({'ok': False, 'error': 'wrong_game_type', 'game_type': getattr(g, 'game_type', None)}, status_code=409)
    if (getattr(g, 'status', '') or '').lower() == 'ended':
        return JSONResponse({'ok': False, 'ended': True}, status_code=409)

    # Guard: do not allow controlling Spotify playback before the game has started.
    if (getattr(g, 'status', '') or '') != 'started':
        return JSONResponse({'error': 'Game not started (press Start Game first)'}, status_code=400)
    # Determine the playlist context URI stored on the game.
    playlist_uri = (
        getattr(g, 'playlist_uri', '') or
        getattr(g, 'spotify_playlist_uri', '') or
        getattr(g, 'spotify_playlist', '') or
        ''
    )
    if not playlist_uri:
        pid = (
            getattr(g, 'spotify_playlist_id', '') or
            getattr(g, 'playlist_id', '') or
            getattr(g, 'playlist', '') or
            ''
        )
        if pid:
            if str(pid).startswith('spotify:'):
                playlist_uri = str(pid)
            else:
                playlist_uri = 'spotify:playlist:' + str(pid)

    if not playlist_uri:
        return JSONResponse({'error': 'No playlist configured for this game'}, status_code=400)

    # Only the FIRST Play of a game restarts the playlist at a random spot. Later Plays (a second click
    # while the first request is still in flight, or Play after a host page reload) just resume;
    # otherwise playback jumps to a different song and a song nobody heard gets recorded as played.
    with _PLAY_RESTART_LOCK:
        already_played = db.query(models.PlayedTrack.id).filter(models.PlayedTrack.game_id == g.id).first() is not None
        recently_restarted = (time.monotonic() - _PLAY_RESTARTED_AT.get(code_u, float('-inf'))) < 30
        restart = not (already_played or recently_restarted)
        if restart:
            _PLAY_RESTARTED_AT[code_u] = time.monotonic()
    if not restart:
        try:
            qdev = (device_id or '').strip()
            spotify.api_put(db, f"/me/player/play?device_id={quote(qdev)}" if qdev else "/me/player/play", None, host_user_id=uid)
            return JSONResponse({'ok': True, 'restarted': False, 'resumed': True})
        except Exception as e:
            return JSONResponse({'error': str(e)}, status_code=400)

    # Always start a NEW session at the beginning, and (if shuffle is used) force a fresh shuffle order.
    try:
        from urllib.parse import quote as _q

        qdev = (device_id or '').strip()
        # Random start: choose a random track position in the playlist (so each game does NOT start at track 1).
        rand_pos = 0
        try:
            import random as _random
            pid = ''
            if isinstance(playlist_uri, str) and playlist_uri.startswith('spotify:playlist:'):
                pid = playlist_uri.split(':')[-1]
            if pid:
                meta = spotify.api_get(db, f"/playlists/{pid}", host_user_id=uid)
                total = int((((meta or {}).get('tracks') or {}).get('total') or 0))
                if total > 0:
                    rand_pos = int(_random.randrange(total))
        except Exception as e:
            log_swallowed(e)
            rand_pos = 0

        if qdev:
            # Toggling shuffle off -> on is the most reliable way to force Spotify to create a new shuffled order.
            with best_effort():
                spotify.api_put(db, f"/me/player/shuffle?state=false&device_id={_q(qdev)}", host_user_id=uid)
            with best_effort():
                spotify.api_put(db, f"/me/player/shuffle?state=true&device_id={_q(qdev)}", host_user_id=uid)

            spotify.api_put(db, f"/me/player/play?device_id={_q(qdev)}", {
                "context_uri": playlist_uri,
                "offset": {"position": rand_pos},
                "position_ms": 0
            }, host_user_id=uid)
        else:
            # No device_id specified; still reset playback position and context.
            spotify.api_put(db, "/me/player/play", {
                "context_uri": playlist_uri,
                "offset": {"position": rand_pos},
                "position_ms": 0
            }, host_user_id=uid)

        # Starting a new context can reset shuffle, so set shuffle and repeat AFTER play. Repeat is
        # "context" rather than "off": with repeat off, reaching the end of the playlist hands over to
        # Spotify Autoplay, whose songs aren't on anyone's card. Songs only count once, and the
        # end-of-playlist check in track_update stops the game once every song has played.
        dev_q = f"&device_id={_q(qdev)}" if qdev else ""
        for path in (f"/me/player/shuffle?state=true{dev_q}", f"/me/player/repeat?state=context{dev_q}"):
            for attempt in range(3):
                with best_effort():
                    time.sleep(0.4 if attempt == 0 else 0.8)
                    spotify.api_put(db, path, host_user_id=uid)
                    break

        return JSONResponse({'ok': True, 'restarted': True})
    except Exception as e:
        return JSONResponse({'error': str(e)}, status_code=400)


@router.post('/host/game/{code}/spotify/pause')
def host_pause(request: Request, code: str, device_id: str = '', db: Session = Depends(get_db)):
    r = require_host(request)
    if r:
        return r

    u = None
    try:
        u = _host_user_from_session(request, db)
    except Exception:
        u = None
    if not u:
        return RedirectResponse(url="/login?next=/host", status_code=302)

    uid = int(getattr(u, 'id', 0) or 0) or None
    owner_key = _owner_key_for_user(u)
    code_u = (code or '').strip().upper()

    g = (db.query(models.Game)
         .filter(models.Game.code == code_u,
                 models.Game.owner_key == owner_key,
                 models.Game.game_type == 'hosted')
         .first())
    if not g:
        return JSONResponse({'error': 'Game not found'}, status_code=404)

    # hosted games only
    if (getattr(g, 'game_type', '') or '').lower() != 'hosted':
        return JSONResponse({'ok': False, 'error': 'wrong_game_type', 'game_type': getattr(g, 'game_type', None)}, status_code=409)

    # Pausing is always allowed once the game has started, including after it ended (music kept playing
    # after End Game and the host couldn't stop it).
    if (getattr(g, 'status', '') or '').lower() not in ('started', 'ended'):
        return JSONResponse({'error': 'Game not started (press Start Game first)'}, status_code=400)

    try:
        spotify.api_put(db, on_device('/me/player/pause', device_id), host_user_id=uid)
        return JSONResponse({'ok': True})
    except Exception as e:
        return JSONResponse({'error': str(e)}, status_code=400)


_NEXT_MIN_GAP_S = 1.5


_NEXT_LAST = {}


_NEXT_LOCK = threading.Lock()


@router.post('/host/game/{code}/spotify/next')
def host_next(request: Request, code: str, device_id: str = '', db: Session = Depends(get_db)):
    r = require_host(request)
    if r:
        return r

    u = None
    try:
        u = _host_user_from_session(request, db)
    except Exception:
        u = None
    if not u:
        return RedirectResponse(url="/login?next=/host", status_code=302)

    uid = int(getattr(u, 'id', 0) or 0) or None
    owner_key = _owner_key_for_user(u)
    code_u = (code or '').strip().upper()

    g = (db.query(models.Game)
         .filter(models.Game.code == code_u,
                 models.Game.owner_key == owner_key,
                 models.Game.game_type == 'hosted')
         .first())
    if not g:
        return JSONResponse({'error': 'Game not found'}, status_code=404)

    # hosted games only
    if (getattr(g, 'game_type', '') or '').lower() != 'hosted':
        return JSONResponse({'ok': False, 'error': 'wrong_game_type', 'game_type': getattr(g, 'game_type', None)}, status_code=409)
    if (getattr(g, 'status', '') or '').lower() == 'ended':
        return JSONResponse({'ok': False, 'ended': True}, status_code=409)

    if (getattr(g, 'status', '') or '') != 'started':
        return JSONResponse({'error': 'Game not started (press Start Game first)'}, status_code=400)

    # A second Next right after the first (double click, held key, another tab) would skip a song nobody heard
    # and put it in the played list: ignore it.
    now_m = time.monotonic()
    with _NEXT_LOCK:
        if now_m - _NEXT_LAST.get(code_u, -1e9) < _NEXT_MIN_GAP_S:
            return JSONResponse({'ok': True, 'throttled': True})
        _NEXT_LAST[code_u] = now_m

    try:
        # Best-effort: if we've already played >= playlist total, PAUSE instead of skipping into recommendations.
        with best_effort():
            pid = (getattr(g, 'spotify_playlist_id', '') or getattr(g, 'playlist_id', '') or '').strip()
            code_key = (code_u or '').strip().upper()
            _ids, _total = _bingo_get_playlist_track_ids(db, host_user_id=uid, playlist_uri_or_id=pid, code_u=code_key, cache_ttl_s=60)
            _last = db.query(models.PlayedTrack).filter(models.PlayedTrack.game_id == g.id).order_by(models.PlayedTrack.seq.desc()).first()
            _seq = int(getattr(_last, 'seq', 0) or 0)
            if int(_total or 0) > 0 and _seq >= int(_total or 0):
                with best_effort():
                    spotify.api_put(db, on_device('/me/player/pause', device_id), host_user_id=uid)
                # Only signal end-of-playlist if playlist total is reliable (>=24) AND we've played through it.
                try:
                    __eop_total = int((_total or 0))
                    __eop_seq   = int((_seq   or 0))
                except Exception:
                    __eop_total = 0
                    __eop_seq   = 0
                if __eop_total >= 24 and __eop_seq >= __eop_total:
                    return JSONResponse({'ok': True, 'end_of_playlist': True, 'total': int(_total or 0), 'seq': int(_seq)})

        with best_effort():
            # If we've already recorded all tracks from the playlist, don't let Spotify advance into recommendations.

            playlist_id = (getattr(g, 'spotify_playlist_id', '') or '').strip()

            ids, total = _bingo_get_playlist_track_ids(db, uid, playlist_id, code_u=code_u, cache_ttl_s=60)

            last = db.query(models.PlayedTrack).filter(models.PlayedTrack.game_id == g.id).order_by(models.PlayedTrack.seq.desc()).first()

            seq = int(getattr(last, 'seq', 0) or 0)

            if total and seq >= total:
                with best_effort():
                    spotify.api_put(db, on_device('/me/player/pause', device_id), host_user_id=uid)

                with best_effort():
                    awaitable = hub.broadcast_host(code_u, {'type': 'end_of_playlist', 'paused': True, 'total': int(total), 'played': int(seq)})

                    # hub.broadcast_host is async in some builds; tolerate either.

                    with best_effort():
                        import asyncio as _asyncio

                        if _asyncio.iscoroutine(awaitable):
                            _asyncio.get_event_loop().create_task(awaitable)

                # Only signal end-of-playlist if playlist total is reliable (>=24) AND we've played through it.
                try:
                    __eop_total = int((total or 0))
                    __eop_seq   = int((seq   or 0))
                except Exception:
                    __eop_total = 0
                    __eop_seq   = 0
                if __eop_total >= 24 and __eop_seq >= __eop_total:
                    return JSONResponse({'ok': True, 'end_of_playlist': True, 'paused': True, 'total': int(total), 'played': int(seq)})

        spotify.api_post(db, on_device('/me/player/next', device_id), host_user_id=uid)
        return JSONResponse({'ok': True})
    except Exception as e:
        return JSONResponse({'ok': True, 'warning': str(e)})


@router.post('/host/game/{code}/track_update')
async def host_track_update(request: Request, code: str, db: Session = Depends(get_db)):
    r = require_host(request)
    if r:
        return JSONResponse({'error': 'not authed'}, status_code=401)

    u = _host_user_from_session(request, db)
    if not u:
        return JSONResponse({'error': 'Not logged in'}, status_code=401)
    owner_key = _owner_key_for_user(u)
    code_u = (code or '').strip().upper()
    g = (db.query(models.Game)
         .filter(models.Game.code == code_u, models.Game.owner_key == owner_key, models.Game.game_type == 'hosted')
         .first())
    if not g:
        return JSONResponse({'error': 'Game not found'}, status_code=404)

    # Guard: do not mutate per-game state from embedded-player updates unless the game is started.
    # This prevents a previously-playing Spotify session from leaking into a newly created game.
    if (getattr(g, 'status', '') or '') != 'started':
        return JSONResponse({'ok': True, 'is_new': False, 'ignored': True})

    # Enforce that Spotify is playing FROM this game's playlist context.
    # If Spotify drifted to recommendations / a different context, ignore updates so we don't pollute played history.
    with best_effort():
        u = None
        try:
            u = _host_user_from_session(request, db)
        except Exception:
            u = None
        uid = int(getattr(u, 'id', 0) or 0) or None
        if uid:
            st = await run_in_threadpool(spotify.api_get, db, '/me/player', host_user_id=uid) or {}
            ctx_uri = ((st.get('context') or {}).get('uri') or '')
            expected = 'spotify:playlist:' + str(getattr(g, 'spotify_playlist_id', '') or '').strip()
            if expected and ctx_uri and ctx_uri != expected:
                # Ignore only; do NOT pause. Right after Play, Spotify's API can still report the previous
                # playlist for a moment, and pausing here stopped the new game's first song.
                _log_ignored_once(code_u, "wrong_context", ctx_uri, f"spotify context={ctx_uri} expected={expected}; ignored")
                return JSONResponse({'ok': True, 'is_new': False, 'ignored': True, 'wrong_context': True})

    try:
        payload = await request.json()
    except Exception:
        return JSONResponse({'error': 'Bad JSON'}, status_code=400)

    track_id = (payload.get('track_id') or '').strip()
    title = (payload.get('title') or '').strip()
    title = _bingo_clean_title_display(title)

    artist = (payload.get('artist') or '').strip()

    # If Spotify reports a track that is not in the playlist, pause and signal end_of_playlist.

    with best_effort():
        # Always use the playlist id from the game record.

        _pid = (getattr(g, 'spotify_playlist_id', '') or '').strip()

        _ids, _total = _bingo_get_playlist_track_ids(db, uid, _pid, code_u=code_u, cache_ttl_s=60)

        # NOTE: Spotify can report track IDs that don't match playlist fetch IDs (relinks/market/linked_from).
        # We do NOT treat this as End-of-Playlist. We simply ignore this update to avoid premature EOP.
        # True End-of-Playlist is determined elsewhere using played-count vs playlist total.
        if track_id and _ids and (track_id not in _ids):
            _log_ignored_once(code_u, "non_playlist_track", track_id,
                              f"title={title!r} artist={artist!r} track_id={track_id} (not in playlist {_pid}; possibly a relinked version)")
            return JSONResponse({'ok': True, 'ignored': True, 'non_playlist_track': True})


# position/paused are optional but important for player reveal timing
    try:
        position_ms = int(payload.get('position_ms') or 0)
    except Exception:
        position_ms = 0
    paused = bool(payload.get('paused', False))

    if not title and not track_id:
        return JSONResponse({'ok': False, 'ignored': True})

    last = db.query(models.PlayedTrack).filter(
        models.PlayedTrack.game_id == g.id
    ).order_by(models.PlayedTrack.seq.desc()).first()

    # Guard: if this would be the FIRST recorded track for the game, only ignore clearly-stale states.
# We allow mid-track playback (position_ms > 5s) so the UI shows the current track immediately.
    if last is None:
        try:
            if paused:
                _log_ignored_once(code_u, "first_track_paused", track_id or title, f"title={title!r} (first song arrived paused; waiting for play)")
                return JSONResponse({'ok': True, 'is_new': False, 'ignored': True})
        except Exception:
            return JSONResponse({'ok': True, 'is_new': False, 'ignored': True})

    # Determine if this update represents a NEW track for the game.
    is_new = True

    # 1) Heartbeat for the current track (same track_id as last) => not new
    if last and track_id and getattr(last, 'spotify_track_id', '') == track_id:
        is_new = False

    # 2) No track_id fallback: compare normalized title keys
    if is_new and last and (not track_id) and normalize_key(last.title) == normalize_key(clean_title_for_card(title)):
        is_new = False

    # 3) If this track_id was played earlier in this game, do NOT add it again.
    #    IMPORTANT: We do NOT auto-skip here (that caused runaway skipping).
    if is_new and track_id:
        with best_effort():
            already = db.query(models.PlayedTrack).filter(
                models.PlayedTrack.game_id == g.id,
                models.PlayedTrack.spotify_track_id == track_id
            ).first()
            if already:
                is_new = False

    seq = (last.seq + 1) if (last and is_new) else (last.seq if last else 0)

    if is_new:
        db.add(models.PlayedTrack(
            game_id=g.id,
            seq=seq,
            spotify_track_id=track_id,
            title=clean_title_for_card(title),
            artist=artist
        ))
        db.commit()

    import time as _time
    server_ts_ms = int(_time.time() * 1000)

    # Broadcast what Spotify says is currently playing (even if it's a duplicate),
    # but only increment the game's played list/counters when is_new == True.
    msg = {
        'type': 'track',
        'title': _bingo_clean_title_display(title) if title else (_bingo_clean_title_display(last.title) if last else ''),
        'artist': artist if artist else (last.artist if last else ''),
        'track_id': track_id or (getattr(last, 'spotify_track_id', '') if last else ''),
        'position_ms': position_ms,
        'paused': bool(paused),
        'server_ts_ms': server_ts_ms,
        'duplicate_ignored': (not is_new),
    }

    with best_effort():
        # Store a shallow copy so later mutations don't affect cached state
        LAST_TRACK_STATE[code_u] = dict(msg)

    await hub.broadcast_players(code, msg)
    await hub.broadcast_host(code, msg)

    if is_new:
        await hub.broadcast_host(code, {'type': 'played_updated'})
        await hub.broadcast_host(code, {'type': 'songs_count', 'count': seq})

    return JSONResponse({'ok': True, 'is_new': bool(is_new)})
