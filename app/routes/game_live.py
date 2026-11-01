"""Host: the live game page and its lifecycle: players (admit/kick), start, continue, end, QR page, hint mode and the live socket."""
import sqlalchemy as sa
from fastapi import APIRouter, Depends, Request, WebSocket
from datetime import datetime
from starlette.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.websockets import WebSocketDisconnect
from sqlalchemy.orm import Session
from ..db import SessionLocal, get_db
from .. import models, spotify, settings
from ..ws import hub
from ..cards import WIN_PATTERNS, _admit_with_card, _card_title_pool, pattern_info, pattern_key
from ..common import on_device, _current_round, _host_user_from_session, _host_user_id_from_game, _norm_code, _owned_game, _owner_key_for_user, _upper_code, require_host, templates
from ..paper import PAPER_MAX_CARDS
from ..scoreboard import scoreboard
from ..errors import best_effort, rollback_quietly

router = APIRouter()


@router.get('/host/game/{code}', response_class=HTMLResponse)
def host_game_page(request: Request, code: str, db: Session = Depends(get_db)):
    r = require_host(request)
    if r:
        return r

    u = _host_user_from_session(request, db)
    owner_key = _owner_key_for_user(u)
    uid = int(getattr(u, 'id', 0) or 0) or None

    g = db.query(models.Game).filter(
        models.Game.code == code,
        models.Game.owner_key == owner_key,
        models.Game.game_type == 'hosted'
    ).first()
    if not g:
        return HTMLResponse('Game not found', status_code=404)

    players = (db.query(models.Player)  # phone players only; paper cards have their own panel
                 .filter(models.Player.game_id == g.id, models.Player.is_paper == sa.false())
                 .order_by(models.Player.created_at.asc()).all())
    played = db.query(models.PlayedTrack).filter(models.PlayedTrack.game_id == g.id).order_by(models.PlayedTrack.seq.desc()).limit(100).all()
    # Include rejected claims so the host keeps a record of them (the template labels them "Rejected").
    q = db.query(models.BingoClaim).filter(models.BingoClaim.game_id == g.id)
    claims = q.order_by(models.BingoClaim.created_at.desc()).limit(50).all()
    # Several players can call bingo on the same song. Claims of the current round are ranked by who clicked
    # first (rank, and seconds behind the first) and listed first-come-first-served, ahead of the older history.
    claim_banner = ''
    try:
        cur = _current_round(g)
        # Only claims still in play compete: pending ones, and one already accepted this round. A rejected claim
        # (or one from before a Continue) says nothing about who was first, and a player counts once.
        pool, seen = [], set()
        for c in sorted([c for c in claims if int(getattr(c, 'claim_round', 0) or 0) == cur and (c.status or '') in ('pending', 'accepted')],
                        key=lambda c: (c.created_at, c.id)):
            if c.player_id in seen:
                continue
            seen.add(c.player_id)
            pool.append(c)
        for i, c in enumerate(pool):
            c.rank = i + 1
        pending_now = sorted([c for c in pool if (c.status or '') == 'pending'], key=lambda c: c.rank)
        if len(pool) >= 2 and pending_now:
            first = pool[0]
            names = ', '.join(c.player.name for c in pool[1:3]) + (' and others' if len(pool) > 3 else '')
            claim_banner = f"{len(pool)} players called bingo this round. {first.player.name} clicked first; {names} followed."
        ids_now = {c.id for c in pending_now}
        claims = pending_now + [c for c in claims if c.id not in ids_now]
    except Exception as e:
        print(f"CLAIM_RANK_FAILED game={getattr(g, 'code', '')}: {e!r}")

    # Playlist info for host UI (best-effort)
    playlist_name = None
    playlist_track_total = None
    with best_effort():
        if uid and getattr(g, 'spotify_playlist_id', None):
            pl_meta = spotify.api_get(db, f'/playlists/{g.spotify_playlist_id}', params={'market': 'US'}, host_user_id=uid)
            playlist_name = (pl_meta or {}).get('name')
            playlist_track_total = ((pl_meta or {}).get('tracks') or {}).get('total')

    # Persist playlist_name on the game for downstream templates (best-effort; ignore DB errors)
    try:
        if playlist_name and (getattr(g, 'playlist_name', None) != playlist_name):
            g.playlist_name = playlist_name
            db.commit()
    except Exception:
        rollback_quietly(db)

    host_user_id = uid
    spotify_connected = bool(spotify.get_valid_access_token(db, host_user_id=host_user_id))

    return templates.TemplateResponse(request, 'host_game.html', {
        'request': request,
        'public_base': settings.public_base(),
        'game': g,
        'playlist_name': playlist_name,
        'playlist_track_total': playlist_track_total,
        'players': players,
        'played': played,
        'claims': claims,
        'spotify_connected': spotify_connected,
        'spotify_client_id': settings.spotify_client_id(),
        'notice': request.query_params.get('notice'),
        'paper_count': db.query(sa.func.count(models.Player.id)).filter(models.Player.game_id == g.id, models.Player.is_paper == sa.true()).scalar() or 0,
        'hint_mode': (getattr(g, 'hint_mode', 'off') or 'off'),
        'pattern': pattern_info(g.win_pattern),
        'round_no': _current_round(g) + 1,
        'room_reveal': bool(getattr(g, 'room_reveal', False)),
        'room_sound': bool(getattr(g, 'room_sound', False)),
        'claim_banner': claim_banner,
        'paper_max': PAPER_MAX_CARDS,
    })


def _broadcast_players_changed(code, extra=None):
    from anyio import from_thread
    async def _bcast():
        await hub.broadcast_host(code, {'type': 'players_updated'})
        await hub.broadcast_players(code, extra or {'type': 'admitted'})
    from_thread.run(_bcast)


@router.post('/host/game/{code}/admit_all')
def host_admit_all(request: Request, code: str, db: Session = Depends(get_db)):
    r = require_host(request)
    if r:
        return r
    g = _owned_game(request, db, code)
    if not g:
        return JSONResponse({'error': 'Game not found'}, status_code=404)

    # Players who joined before the game started may still be waiting; the host can admit them while it is running
    # (new people can't join a started game). Nobody is admitted once the game has ended.
    if (getattr(g, 'status', '') or '') == 'ended':
        return JSONResponse({'error': 'Game already ended'}, status_code=409)
    u = _host_user_from_session(request, db)
    uid = int(u.id) if u else None
    uniq, err = _card_title_pool(db, g, uid)
    if err:
        return err

    players = (db.query(models.Player)  # phone players only (paper cards need no admitting)
                 .filter(models.Player.game_id == g.id, models.Player.is_paper == sa.false())
                 .order_by(models.Player.number.asc()).all())
    for p in players:
        if not _admit_with_card(db, p, uniq):
            db.rollback()
            return JSONResponse({'error': 'Could not sample 24 unique tracks from playlist'}, status_code=400)
    db.commit()
    _broadcast_players_changed(code)
    return JSONResponse({'ok': True})


def _phone_player(db, g, number):
    return (db.query(models.Player)
              .filter(models.Player.game_id == g.id, models.Player.number == int(number), models.Player.is_paper == sa.false()).first())


@router.post('/host/game/{code}/player/{number}/admit')
def host_admit_player(request: Request, code: str, number: int, db: Session = Depends(get_db)):
    r = require_host(request)
    if r:
        return r
    g = _owned_game(request, db, code)
    if not g:
        return JSONResponse({'error': 'Game not found'}, status_code=404)
    if (getattr(g, 'status', '') or '') == 'ended':
        return JSONResponse({'error': 'Game already ended'}, status_code=409)
    p = _phone_player(db, g, number)
    if not p:
        return JSONResponse({'error': 'Player not found'}, status_code=404)
    u = _host_user_from_session(request, db)
    uniq, err = _card_title_pool(db, g, int(u.id) if u else None)
    if err:
        return err
    if not _admit_with_card(db, p, uniq):
        db.rollback()
        return JSONResponse({'error': 'Could not sample 24 unique tracks from playlist'}, status_code=400)
    db.commit()
    _broadcast_players_changed(code)
    return JSONResponse({'ok': True})


@router.post('/host/game/{code}/player/{number}/kick')
def host_kick_player(request: Request, code: str, number: int, db: Session = Depends(get_db)):
    """Remove a phone player (and their card and bingo claims) from a game that hasn't ended."""
    r = require_host(request)
    if r:
        return r
    g = _owned_game(request, db, code)
    if not g:
        return JSONResponse({'error': 'Game not found'}, status_code=404)
    if (getattr(g, 'status', '') or '') == 'ended':
        return JSONResponse({'error': 'Game already ended'}, status_code=409)
    p = _phone_player(db, g, number)
    if not p:
        return JSONResponse({'error': 'Player not found'}, status_code=404)
    n = int(p.number)
    db.query(models.CardSquare).filter(models.CardSquare.player_id == p.id).delete(synchronize_session=False)
    db.query(models.BingoClaim).filter(models.BingoClaim.player_id == p.id).delete(synchronize_session=False)
    db.delete(p)
    db.commit()
    _broadcast_players_changed(code, {'type': 'removed', 'number': n})
    from anyio import from_thread
    async def _claims():
        await hub.broadcast_host(code, {'type': 'claims_updated'})
    from_thread.run(_claims)
    return JSONResponse({'ok': True})


@router.post('/host/game/{code}/start')
async def host_start_game(request: Request, code: str, db: Session = Depends(get_db)):
    r = require_host(request)
    if r:
        return r
    g = _owned_game(request, db, code)
    # Do not allow a game to be started again after it has ended.
    with best_effort():
        if (getattr(g, 'status', '') or '').lower() == 'ended':
            return JSONResponse({'ok': False, 'error': 'ended'}, status_code=409)

    if not g:
        return JSONResponse({'error': 'Game not found'}, status_code=404)

    # Idempotent: if already started, do not restart / re-broadcast / reset timestamps.
    if (getattr(g, 'status', '') or '') == 'started':
        return JSONResponse({'ok': True, 'already_started': True, 'device_id': (getattr(g, 'playback_device_id', '') or '')})

    # Determine chosen playback device:
    #  1) query param device_id
    #  2) JSON body {device_id:"..."}
    #  3) previously stored on game.playback_device_id
    device_id = ''
    try:
        device_id = (request.query_params.get('device_id') or '').strip()
    except Exception:
        device_id = ''

    if not device_id:
        with best_effort():
            body = await request.json()
            if isinstance(body, dict):
                device_id = (body.get('device_id') or '').strip()

    if not device_id:
        device_id = (getattr(g, 'playback_device_id', '') or '').strip()

    if not device_id:
        return JSONResponse({'error': 'Playback device not set. Pick a device in the dropdown, or leave it on Embedded.'}, status_code=400)

    # Persist device choice on the game (for later resume/pause/next)
    with best_effort():
        g.playback_device_id = device_id
    with best_effort():
        g.playback_started_at = datetime.utcnow()

    g.status = 'started'
    g.started_at = datetime.utcnow()
    g.sessions_played = int(g.sessions_played or 0) + 1   # for "played N times" on the Saved Games page
    g.last_played_at = g.started_at
    db.commit()

    async def _bcast():
        await hub.broadcast_host(code, {'type': 'game_started'})
        await hub.broadcast_players(code, {'type': 'game_started'})
    await _bcast()
    return JSONResponse({'ok': True, 'device_id': device_id})


@router.websocket('/ws/host/game/{code}')
async def ws_host_game(websocket: WebSocket, code: str):
    code_u = _upper_code(code)

    # Authenticate host via signed cookie AND require that this host owns the game
    db = SessionLocal()
    try:
        owned = _owned_game(websocket, db, code_u) is not None
    finally:
        db.close()
    if not owned:
        # Close without accept => handshake rejected (shows as 403 in uvicorn logs)
        await websocket.close(code=1008)
        return

    await hub.connect_host(code_u, websocket)
    try:
        while True:
            # We don't require messages; this keeps the connection alive and lets us
            # notice disconnects cleanly.
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        await hub.disconnect_host(code_u, websocket)


@router.post("/host/game/{code}/continue_game")
async def host_continue_game(request: Request, code: str, db: Session = Depends(get_db)):
    """
    Host clicks "Continue Game" after a bingo is accepted.
    Broadcast to all players to clear overlays + reset claim UI.
    """
    r = require_host(request)
    if r:
        return r
    code_u = _upper_code(_norm_code(code))
    g = _owned_game(request, db, code_u)
    if not g:
        return JSONResponse({"ok": False, "error": "Game not found"}, status_code=404)
    try:
        body = await request.json()
    except Exception:
        body = {}
    new_pattern = pattern_key((body or {}).get('pattern')) if isinstance(body, dict) and (body or {}).get('pattern') else None
    with best_effort():
        if g:
            try:
                if new_pattern:
                    g.win_pattern = new_pattern   # the next round can be a different shape
                g.continue_seq = int(getattr(g, 'continue_seq', 0) or 0) + 1
                db.add(g)
                db.commit()
            except Exception:
                db.rollback()
        seq = int(getattr(g, 'continue_seq', 0) or 0) if g else 0
        await hub.broadcast_players(code_u, {"type": "continue", "continue_seq": seq})
        await _broadcast_pattern(code_u, g)
        await hub.broadcast_players(code_u, {"type": "overlay", "overlay": "clear"})
        await hub.broadcast_host(code_u, {"type": "room", "event": "clear"})
    return JSONResponse({"ok": True})


@router.post("/host/game/{code}/end_game")
async def host_end_game(request: Request, code: str, device_id: str = '', db: Session = Depends(get_db)):
    # Host clicks "End Game" after a bingo is accepted.
    r = require_host(request)
    if r:
        return r
    code_u = _upper_code(_norm_code(code))
    g = _owned_game(request, db, code_u)
    if not g:
        return JSONResponse({"ok": False, "error": "Game not found"}, status_code=404)
    # hosted games only
    if (getattr(g, 'game_type', '') or '').lower() != 'hosted':
        return JSONResponse({'ok': False, 'error': 'wrong_game_type', 'game_type': getattr(g, 'game_type', None)}, status_code=409)
    if (getattr(g, 'status', '') or '').lower() == 'ended':
        return JSONResponse({'ok': False, 'ended': True}, status_code=409)
    with best_effort():
        if g:
            try:
                setattr(g, "status", "ended")
                db.add(g)
                db.commit()
            except Exception:
                db.rollback()
        # Stop the music: ending the game used to leave Spotify playing.
        try:
            await run_in_threadpool(spotify.api_put, db, on_device('/me/player/pause', device_id), host_user_id=_host_user_id_from_game(g))
        except Exception as e:
            print(f"END_GAME_PAUSE_FAILED game={code_u}: {e!r}")
        with best_effort():
            await hub.broadcast_players(code_u, {"type": "end_game"})
        with best_effort():
            await hub.broadcast_players(code_u, {"type": "overlay", "overlay": "game_over"})
        with best_effort():
            await hub.broadcast_host(code_u, {"type": "room", "event": "game_over"})
    return JSONResponse({"ok": True})


async def _broadcast_pattern(code_u, g):
    """Tell every phone and host page which pattern counts as bingo now."""
    msg = {'type': 'pattern', 'round': _current_round(g) + 1, **pattern_info(g.win_pattern)}
    await hub.broadcast_players(code_u, msg)
    await hub.broadcast_host(code_u, msg)


def _pattern_change_allowed(db, g) -> bool:
    """The pattern can change before the game starts, or between rounds (once a bingo has been accepted in this one)."""
    st = (g.status or '').lower()
    if st == 'lobby':
        return True
    if st != 'started':
        return False
    return db.query(models.BingoClaim.id).filter(models.BingoClaim.game_id == g.id, models.BingoClaim.claim_round == _current_round(g),
                                                 models.BingoClaim.status == 'accepted').first() is not None


@router.post('/host/game/{code}/pattern')
async def host_win_pattern(request: Request, code: str, db: Session = Depends(get_db)):
    # What counts as bingo from now on (claims already made keep the pattern they were made under)
    r = require_host(request)
    if r:
        return r
    g = _owned_game(request, db, _upper_code(_norm_code(code)))
    if not g:
        return JSONResponse({'ok': False, 'error': 'Game not found'}, status_code=404)
    try:
        body = await request.json()
    except Exception:
        body = {}
    key = str((body or {}).get('pattern') or '').strip().lower() if isinstance(body, dict) else ''
    if key not in WIN_PATTERNS:
        return JSONResponse({'ok': False, 'error': 'Unknown pattern'}, status_code=400)
    if not _pattern_change_allowed(db, g):
        return JSONResponse({'ok': False, 'error': 'The pattern is locked while a round is being played. Change it before the game starts, or after a bingo is accepted.'}, status_code=409)
    g.win_pattern = key
    db.add(g)
    db.commit()
    with best_effort():
        await _broadcast_pattern(g.code, g)
    return JSONResponse({'ok': True, 'round': _current_round(g) + 1, **pattern_info(key)})


@router.post('/host/game/{code}/hint_mode')
async def host_hint_mode(request: Request, code: str, db: Session = Depends(get_db)):
    # Bingo hints for this game: off, on for everyone, or each phone player chooses
    r = require_host(request)
    if r:
        return r
    g = _owned_game(request, db, _upper_code(_norm_code(code)))
    if not g:
        return JSONResponse({'ok': False, 'error': 'Game not found'}, status_code=404)
    try:
        body = await request.json()
    except Exception:
        body = {}
    mode = str((body or {}).get('mode') or '').strip().lower()
    if mode not in ('off', 'all', 'optin'):
        return JSONResponse({'ok': False, 'error': 'mode must be off, all or optin'}, status_code=400)
    g.hint_mode = mode
    db.add(g)
    db.commit()
    with best_effort():
        await hub.broadcast_players(g.code, {'type': 'hint_mode', 'mode': mode})
    return JSONResponse({'ok': True, 'mode': mode})


@router.post('/host/game/{code}/room_reveal')
async def host_room_reveal(request: Request, code: str, db: Session = Depends(get_db)):
    # Option: the QR screen turns into a song-reveal screen for the room once the game starts
    r = require_host(request)
    if r:
        return r
    g = _owned_game(request, db, _upper_code(_norm_code(code)))
    if not g:
        return JSONResponse({'ok': False, 'error': 'Game not found'}, status_code=404)
    try:
        body = await request.json()
    except Exception:
        body = {}
    body = body if isinstance(body, dict) else {}
    if 'on' in body:
        g.room_reveal = bool(body.get('on'))
    if 'sound' in body:       # also play the game music through the QR screen's browser
        g.room_sound = bool(body.get('sound'))
    db.add(g)
    db.commit()
    on, sound = bool(g.room_reveal), bool(g.room_sound)
    with best_effort():
        await hub.broadcast_host(g.code, {'type': 'room_reveal', 'on': on, 'sound': sound})
    return JSONResponse({'ok': True, 'on': on, 'sound': sound})


@router.get('/host/game/{code}/scoreboard', response_class=HTMLResponse)
def host_game_scoreboard(request: Request, code: str, db: Session = Depends(get_db)):
    # Full-screen scoreboard (winner of each round, most wins) to cast to a TV like the QR screen
    r = require_host(request, next_path=f'/host/game/{code}/scoreboard')
    if r:
        return r
    g = _owned_game(request, db, code)
    if not g:
        return RedirectResponse(url='/host', status_code=302)
    return templates.TemplateResponse(request, 'game_scoreboard.html', {'request': request, 'game': g, 'board': scoreboard(db, g)})


@router.get('/host/game/{code}/scoreboard.json')
def host_game_scoreboard_json(request: Request, code: str, db: Session = Depends(get_db)):
    r = require_host(request)
    if r:
        return r
    g = _owned_game(request, db, code)
    if not g:
        return JSONResponse({'error': 'Game not found'}, status_code=404)
    return JSONResponse(scoreboard(db, g))


@router.get('/host/game/{code}/qr', response_class=HTMLResponse)
def host_game_qr(request: Request, code: str, db: Session = Depends(get_db)):
    # Full-screen QR code of the join link, to cast to a TV or projector
    r = require_host(request, next_path=f'/host/game/{code}/qr')
    if r:
        return r
    g = _owned_game(request, db, code)
    if not g:
        return RedirectResponse(url='/host', status_code=302)
    return templates.TemplateResponse(request, 'game_qr.html', {
        'request': request, 'game': g,
        'join_url': f'{settings.public_base()}/game/{g.code}',
        'public_host': settings.public_base().split('://', 1)[-1],
        'room_reveal': bool(getattr(g, 'room_reveal', False)),
        'room_sound': bool(getattr(g, 'room_sound', False)),
        'started': (getattr(g, 'status', '') or '') == 'started',
        'ended': (getattr(g, 'status', '') or '') == 'ended',
    })
