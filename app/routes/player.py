"""Phone players: join a game, the card page, bingo claims and the live-update socket."""
import sqlalchemy as sa
import uuid
import re
from fastapi import APIRouter, Depends, Request, WebSocket
from starlette.concurrency import run_in_threadpool
from starlette.responses import Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.websockets import WebSocketDisconnect
from sqlalchemy.orm import Session
from ..db import SessionLocal, get_db
from .. import models
from ..ws import hub
from ..avatars import choose as choose_avatar
from ..scoreboard import scoreboard
from ..cards import _ensure_card_squares, _fetch_playlist_tracks, _is_bingo, pattern_info, pattern_key
from ..common import _current_round, _host_user_from_session, _host_user_id_from_game, _norm_code, _owner_key_for_user, _player_cookie_name, _player_from_cookie, _upper_code, clear_cookie, set_cookie, templates
from ..paper import paper_display_title
from ..state import LAST_TRACK_STATE
from ..errors import best_effort, log_swallowed, rollback_quietly

router = APIRouter()
MAX_PLAYERS_PER_GAME = 500   # a lobby can't be flooded without limit

# Phone cards print the same tidy title as paper cards (Asian-script extras and bracketed text left out)
templates.env.globals['display_title'] = paper_display_title


@router.get("/game/{code}", response_class=HTMLResponse)
def game_join_page(code: str, request: Request, db: Session = Depends(get_db)):
    orig_code = code
    code = _norm_code(code)
    if code and code != orig_code:
        return RedirectResponse(url=f"/game/{code}", status_code=302)
    code_u=_upper_code(code)
    g=db.query(models.Game).filter(models.Game.code == code_u).first() if code_u else None
    if not g:
        return templates.TemplateResponse(request, "enter_game_code.html", {"request": request, "code": code_u, "error": f"Game {code_u} not found." if code_u else "Game not found."}, status_code=404)

    # A player who already joined (refresh, reopened tab, reused join link) goes back to their card
    # once the game has started, instead of being locked out by "already started".
    me = _player_from_cookie(request, db, g)
    started = (getattr(g, 'status', '') or '') != 'lobby'
    if me and started:
        return RedirectResponse(url=f"/player/{code_u}/{me.number}", status_code=302)

    # Block joining if the game is already started/ended
    if started:
        return templates.TemplateResponse(request, "join_game.html", {"request": request, "game": g, "code": code_u, "error": "Sorry this game has already started.", "join_blocked": True, "error_title": "Sorry this game has already started."}, status_code=409)
    return templates.TemplateResponse(request, "join_game.html", {"request": request, "game": g, "code": code_u, "existing_player": me})


@router.get("/game/{code}/event_logo")
def game_event_logo(code: str, db: Session = Depends(get_db)):
    """The event logo of a game, for the FREE square on the players' cards (the game code is the key; no login)."""
    g = db.query(models.Game).filter(models.Game.code == _upper_code(_norm_code(code))).first()
    vid = getattr(g, 'event_id', None) if g else None
    v = db.query(models.Event).filter(models.Event.id == vid).first() if vid else None
    if not v or not v.logo:
        return Response(status_code=404)
    return Response(content=v.logo, media_type=v.logo_mime or 'image/png', headers={'Cache-Control': 'private, max-age=300'})


def _fetch_tracks_with_own_session(playlist_id, host_user_id):
    """The playlist's songs (cached), fetched in a worker thread with a session of its own that is closed straight after, so
    that players waiting for the first fetch do not each hold a database connection."""
    s = SessionLocal()
    try:
        return _fetch_playlist_tracks(s, playlist_id, market="US", limit=100, host_user_id=host_user_id)
    finally:
        s.close()


@router.post("/game/{code}/join")
async def game_join(code: str, request: Request, db: Session = Depends(get_db)):
    code = code.upper()
    code = _norm_code(code)
    form = await request.form()
    code_u=_upper_code(code)
    name=(form.get("name") or form.get("player") or "").strip()
    if not name:
        g0 = db.query(models.Game).filter(models.Game.code == code_u).first()
        return templates.TemplateResponse(request, "join_game.html", {"request": request, "game": g0, "code": code_u, "error": "Please enter your name."}, status_code=400)

    g=db.query(models.Game).filter(models.Game.code == code_u).first()
    host_user_id = _host_user_id_from_game(g)
    if not g:
        return templates.TemplateResponse(request, "enter_game_code.html", {"request": request, "code": code_u, "error": f"Game {code_u} not found."}, status_code=404)



    # Block joining if the game is already started/ended (but send an existing player back to their card)
    if (getattr(g, 'status', '') or '') != 'lobby':
        me = _player_from_cookie(request, db, g)
        if me:
            return RedirectResponse(url=f"/player/{code_u}/{me.number}", status_code=302)
        return templates.TemplateResponse(request, "join_game.html", {"request": request, "game": g, "code": code_u, "error": "Sorry this game has already started.", "join_blocked": True, "error_title": "Sorry this game has already started."}, status_code=409)

    # Fetch the playlist (blocking Spotify calls) in a worker thread BEFORE any DB writes, so the
    # event loop isn't stalled and no transaction is held open across an await. The card build
    # below then reads from the warm cache.
    playlist_id = g.spotify_playlist_id
    db.rollback()   # hand the database connection back while we wait: dozens of phones join at the same moment
    try:
        await run_in_threadpool(_fetch_tracks_with_own_session, playlist_id, host_user_id)
    except Exception as e:
        print(f"JOIN_PLAYLIST_FETCH_FAILED game={code_u} host_user_id={host_user_id}: {e!r}")
        return templates.TemplateResponse(request, "join_game.html", {"request": request, "game": g, "code": code_u, "error": "Can't build your card right now: the host's Spotify isn't connected or the playlist couldn't be loaded. Please ask the host, then try again."}, status_code=503)

    if db.query(sa.func.count(models.Player.id)).filter(models.Player.game_id == g.id).scalar() >= MAX_PLAYERS_PER_GAME:
        return templates.TemplateResponse(request, "join_game.html", {"request": request, "game": g, "code": code_u, "error": "Sorry, this game is full."}, status_code=409)

    # No awaits from here to commit: player numbering + card insert stay atomic on the event loop.
    max_no = db.query(sa.func.max(models.Player.number)).filter(models.Player.game_id == g.id).scalar() or 0
    next_no = int(max_no) + 1

    token = uuid.uuid4().hex
    taken = [a for (a,) in db.query(models.Player.avatar).filter(models.Player.game_id == g.id).all()]
    pic, pic_color = choose_avatar(form.get("avatar"), form.get("avatar_color"), taken)
    p=models.Player(game_id=g.id, number=next_no, name=name[:40], admitted=False, token=token, avatar=pic, avatar_color=pic_color)
    db.add(p)
    db.flush()

    _ensure_card_squares(db, g, p, host_user_id=host_user_id)
    db.commit()

    # Notify host page to refresh player list (WS)
    with best_effort():
        await hub.broadcast_host(code_u, {'type': 'players_updated'})

    resp=RedirectResponse(url=f"/player/{code_u}/{next_no}", status_code=302)
    # Persistent (2 days), not a session cookie: phone browsers drop session cookies when the
    # browser is closed or evicted, which locked players out of started games.
    set_cookie(request, resp, _player_cookie_name(code_u), token, days=2)
    return resp


@router.post("/game/{code}/not_me")
async def game_not_me(code: str, request: Request, db: Session = Depends(get_db)):
    """"Not you?" on the join page: take the player this browser joined as out of the lobby (so they don't linger in
    the host's list) and forget it, so someone else can join from this phone. Only while the game is in the lobby."""
    code_u = _upper_code(_norm_code(code))
    g = db.query(models.Game).filter(models.Game.code == code_u).first()
    if not g:
        return RedirectResponse(url="/enter", status_code=302)
    me = _player_from_cookie(request, db, g)
    if me and (getattr(g, 'status', '') or '') == 'lobby' and not getattr(me, 'is_paper', False):
        db.query(models.CardSquare).filter(models.CardSquare.player_id == me.id).delete(synchronize_session=False)
        db.query(models.BingoClaim).filter(models.BingoClaim.player_id == me.id).delete(synchronize_session=False)
        db.delete(me)
        db.commit()
        with best_effort():
            await hub.broadcast_host(code_u, {'type': 'players_updated'})
    resp = RedirectResponse(url=f"/game/{code_u}", status_code=302)
    clear_cookie(resp, _player_cookie_name(code_u))
    return resp


@router.get("/player/{code}/{playerno}", response_class=HTMLResponse)
def player_card(code: str, playerno: int, request: Request, db: Session = Depends(get_db)):
    code_u = _upper_code(_norm_code(code))
    if code_u != code:
        return RedirectResponse(url=f"/player/{code_u}/{playerno}", status_code=302)
    g = db.query(models.Game).filter(models.Game.code == code_u).first()
    if not g:
        # Defensive: if someone hits /player/<code>/<n> for a non-existent game
        return templates.TemplateResponse(request, "enter_game_code.html", {"request": request, "code": code_u, "error": f"Game {code_u} not found."}, status_code=404)
    game = g
    host_user_id = _host_user_id_from_game(g)

    p=db.query(models.Player).filter(models.Player.game_id == g.id, models.Player.number == int(playerno)).first()
    if not p:
        return RedirectResponse(url=f"/game/{code_u}", status_code=302)

    cookie=request.cookies.get(_player_cookie_name(code_u))
    if not cookie or cookie != p.token:
        return RedirectResponse(url=f"/game/{code_u}", status_code=302)

    squares=db.query(models.CardSquare).filter(models.CardSquare.player_id == p.id).order_by(models.CardSquare.pos.asc()).all()
    if not squares or len(squares) < 25:
        _ensure_card_squares(db, g, p, host_user_id=host_user_id)
        db.commit()
        squares=db.query(models.CardSquare).filter(models.CardSquare.player_id == p.id).order_by(models.CardSquare.pos.asc()).all()

    # expose claim status (pending vs accepted) to template
    bingo_claimed = False
    bingo_claim_status = ""
    try:
        _c = (db.query(models.BingoClaim)
            .filter(models.BingoClaim.game_id == g.id,
                    models.BingoClaim.claim_round == _current_round(g), models.BingoClaim.player_id == p.id,
                    models.BingoClaim.status.in_(['pending','accepted']))
            .order_by(models.BingoClaim.id.desc())
            .first())
        if _c:
            bingo_claimed = True
            bingo_claim_status = str(getattr(_c, 'status', '') or '')
    except Exception:
        bingo_claimed = False
        bingo_claim_status = ""
    event = None   # the event (name and/or logo) the host chose for this game; shown in the FREE square
    try:
        vid = getattr(game, 'event_id', None)
        row = db.query(models.Event.id, models.Event.name, models.Event.logo.isnot(None)).filter(models.Event.id == vid).first() if vid else None
        if row and (row[1] or row[2]):
            event = {'id': row[0], 'name': row[1] or '', 'has_logo': bool(row[2])}
    except Exception as e:
        log_swallowed(e)
    return templates.TemplateResponse(request, "player_card.html", {
        "event": event,
        "game": game,
        "request": request,
        "current_title": "",
        "current_artist": "",
        "code": code_u,
        "playerno": int(playerno),
        "player": p,
        "admitted": bool(p.admitted),
        "squares": squares,
        'bingo_claimed': bingo_claimed,
        'bingo_claim_status': bingo_claim_status,
        'hint_mode': (getattr(g, 'hint_mode', 'off') or 'off'),
        'pattern': pattern_info(game.win_pattern),
        'round_no': int(game.continue_seq or 0) + 1,
    })


@router.post("/player/{code}/{playerno}/claim_bingo")
async def claim_bingo(code: str, playerno: int, request: Request, db: Session = Depends(get_db)):
    code = _norm_code((code or "").upper())
    code_u = _upper_code(code)

    g = db.query(models.Game).filter(models.Game.code == code_u).first()
    if not g:
        return JSONResponse({"ok": False, "error": "game_not_found"}, status_code=404)


    # NOTE: claim_bingo is used by BOTH hosted and solo games.
    # Only enforce host_session/owner_key/ended checks for SOLO games.
    is_solo = (getattr(g, 'game_type', None) or '') == 'solo'
    if is_solo:
        u = None
        try:
            u = _host_user_from_session(request, db)
        except Exception:
            u = None
        if not u:
            return JSONResponse({'ok': False, 'error': 'forbidden'}, status_code=403)
    
        owner_key = ''
        try:
            owner_key = _owner_key_for_user(u)
        except Exception:
            owner_key = ''
    
        if (getattr(g, 'owner_key', None) or '') != owner_key:
            return JSONResponse({'ok': False, 'error': 'forbidden'}, status_code=403)
        if (getattr(g, 'status', None) or '') == 'ended':
            return JSONResponse({'ok': False, 'ended': True}, status_code=409)

    # Resolve player early (needed for auth + dedupe)
    p = db.query(models.Player).filter(models.Player.game_id == g.id, models.Player.number == int(playerno)).first()
    if not p:
        return JSONResponse({"ok": False, "error": "player_not_found"}, status_code=404)

    cookie = request.cookies.get(_player_cookie_name(code_u))
    if not cookie or cookie != p.token:
        return JSONResponse({"ok": False, "error": "not_authorized"}, status_code=403)
    if not p.admitted:
        # Solo has no host-admit step; allow and persist admission.
        if (getattr(g, 'game_type', None) or '') == 'solo':
            try:
                p.admitted = True
                db.commit()
            except Exception:
                rollback_quietly(db)
        else:
            return JSONResponse({"ok": False, "error": "not_admitted"}, status_code=403)

    # Goals:
    #  1) Within the same round (games.continue_seq), prevent duplicate PENDING claims from same player.
    #  2) Within the same round, prevent reuse after an ACCEPTED claim (no new row).
    #  3) Across rounds, prevent immediate re-claim of the exact same marked pattern that already won before.
    try:
        current_round = int(getattr(g, 'continue_seq', 0) or 0)
    except Exception:
        current_round = 0

    def _mk_sig(mk_set):
        try:
            return ','.join(str(x) for x in sorted(int(v) for v in mk_set))
        except Exception:
            try:
                return ','.join(sorted(str(x) for x in mk_set))
            except Exception:
                return ''

    def _extract_sig(detail_str: str) -> str:
        try:
            if not detail_str:
                return ''
            m = re.search(r'\bmk=([0-9,]+)\b', str(detail_str))
            return m.group(1) if m else ''
        except Exception:
            return ''

    with best_effort():
        existing = (db.query(models.BingoClaim)
                      .filter(models.BingoClaim.game_id == g.id,
                              models.BingoClaim.player_id == p.id,
                              models.BingoClaim.status.in_(['pending','accepted']),
                              models.BingoClaim.claim_round == current_round)
                      .order_by(models.BingoClaim.id.desc()).first())
        if existing:
            st = (getattr(existing, 'status', 'pending') or 'pending').lower().strip()
            if st == 'pending':
                with best_effort():
                    await hub.broadcast_host(code_u, {'type':'claims_updated'})
                    await hub.broadcast_players(code_u, {'type':'claims_updated'})
                return JSONResponse({'ok': True, 'already': True, 'status': 'pending', 'claim_id': getattr(existing,'id',None), 'claim_round': current_round,
                                    'message': 'Bingo already submitted — awaiting host verification'})
            return JSONResponse({'ok': True, 'already': True, 'status': 'accepted', 'claim_id': getattr(existing,'id',None), 'claim_round': current_round,
                                'reuse_blocked': True, 'auto_valid': False, 'message': 'That bingo was already accepted this round'})

    # Parse marked squares from body
    try:
        body = await request.json()
        if not isinstance(body, dict):
            body = {}
    except Exception:
        body = {}

    marked = body.get("marked") if isinstance(body, dict) else []
    if not isinstance(marked, list):
        marked = []

    mk = set()
    for x in marked:
        with best_effort():
            n = int(x)
            if 0 <= n <= 24:
                mk.add(n)
    with best_effort():
        sig_now = _mk_sig(mk)
        if sig_now:
            q2 = (db.query(models.BingoClaim)
                    .filter(models.BingoClaim.game_id == g.id,
                            models.BingoClaim.player_id == p.id,
                            models.BingoClaim.status == 'accepted')
                    .order_by(models.BingoClaim.id.desc()))
            last_acc = q2.first()
            if last_acc:
                last_sig = _extract_sig(getattr(last_acc,'detail','') or '')
                last_round = int(last_acc.claim_round or 0)
                if last_sig and last_sig == sig_now:
                    if last_round != current_round:
                        return JSONResponse({'ok': True, 'already': True, 'status': 'accepted', 'reuse_blocked': True, 'auto_valid': False,
                                            'message': 'You already won with that exact pattern. Mark a different bingo before claiming again.'})



    # Some SOLO clients can send marked positions as 1..25 instead of 0..24.
    # We first test mk as-is; if not a bingo, try shifting down by 1 and re-test.
    # Dev-only debug: capture what the client sent + what the server derived.
    # This helps diagnose mismatched 'marked' indexing or mapping (row/col).
    __solo_debug = {}
    try:
        if is_solo:
            __solo_debug = {
                'dbg_is_solo': True,
                'dbg_marked_raw': marked if isinstance(marked, list) else [],
                'dbg_mk_derived': sorted([int(x) for x in (mk or [])]),
            }
    except Exception:
        __solo_debug = {}

    pattern = pattern_key(getattr(g, 'win_pattern', None)) if not is_solo else 'line'
    line = _is_bingo(mk, pattern)
    if not line:
        with best_effort():
            mk_shift = set()
            for v in (mk or []):
                with best_effort():
                    iv = int(v)
                    if 1 <= iv <= 25:
                        mk_shift.add(iv - 1)
            if mk_shift:
                line2 = _is_bingo(mk_shift, pattern)
                if line2:
                    mk = mk_shift
                    line = line2
    auto_valid = bool(line)
    detail = (f"Auto-valid bingo line: {line}" if line else ("No complete line found." if pattern == 'line' else "No complete pattern found."))
    detail = f"{detail} mk={_mk_sig(mk)}"
    # A bingo is only auto-valid if the songs in the winning line have actually been played in THIS game.
    # This prevents "instant bingo" before tracks are played (applies to BOTH hosted + solo).
    # Data sources:
    # CardSquare titles for this player
    # PlayedTrack rows for this game
    def _norm_title(x):
        try:
            x = (x or "")
            if not isinstance(x, str):
                x = str(x)
            x = x.strip().lower()
        except Exception:
            return ""
        # Keep letters/numbers/spaces only
        out = []
        for ch in x:
            if ch.isalnum() or ch.isspace():
                out.append(ch)
        x = "".join(out)
        x = " ".join(x.split())
        return x

    def _played_norm_titles(game_id: int):
        titles = []
        try:
            rows = db.query(models.PlayedTrack).filter(models.PlayedTrack.game_id == game_id).all()
        except Exception:
            rows = []
        for r in (rows or []):
            raw = ""
            # try common field names defensively
            for k in ("title","track_title","track_name","name","song","text"):
                with best_effort():
                    v = getattr(r, k, "")
                    if isinstance(v, str) and v.strip():
                        raw = v.strip()
                        break
            if raw:
                # if it's "Song — Artist", keep song portion too
                song_part = raw
                if "—" in raw:
                    song_part = raw.split("—", 1)[0].strip()
                elif " - " in raw:
                    song_part = raw.split(" - ", 1)[0].strip()
                elif " – " in raw:
                    song_part = raw.split(" – ", 1)[0].strip()

                n1 = _norm_title(raw)
                n2 = _norm_title(song_part)
                if n1: titles.append(n1)
                if n2 and n2 != n1: titles.append(n2)
        return titles

    def _square_title_by_pos(player_id: int):
        mp = {}
        try:
            sqs = (db.query(models.CardSquare)
                     .filter(models.CardSquare.player_id == player_id)
                     .order_by(models.CardSquare.pos.asc())
                     .all())
        except Exception:
            sqs = []
        for sq in (sqs or []):
            with best_effort():
                mp[int(getattr(sq, "pos", -1))] = str(getattr(sq, "title", "") or "")
        return mp

    # Only apply when we otherwise have an auto-valid line.
    if auto_valid and line:
        try:
            played = _played_norm_titles(int(getattr(g, "id", 0) or 0))
            # SOLO-only: if server has no played tracks recorded yet, accept client-reported played titles
            # (used only to validate auto-valid bingo lines; still prevents instant bingo).
            if (not played) and is_solo:
                with best_effort():
                    pt = body.get('played_titles') if isinstance(body, dict) else None
                    if isinstance(pt, list):
                        tmp = []
                        for raw in pt:
                            with best_effort():
                                s = raw
                                if not isinstance(s, str):
                                    s = str(s)
                                s = (s or '').strip()
                                if not s:
                                    continue
                                # If client sends "Song — Artist" or "Song - Artist", keep song portion ONLY for matching
                                song_part = s
                                if '—' in s:
                                    song_part = s.split('—')[0].strip()
                                elif ' - ' in s:
                                    song_part = s.split(' - ')[0].strip()
                                elif ' – ' in s:
                                    song_part = s.split(' – ')[0].strip()
                                n1 = _norm_title(s)
                                n2 = _norm_title(song_part)
                                if n1:
                                    tmp.append(n1)
                                if n2 and n2 != n1:
                                    tmp.append(n2)
                        if tmp:
                            played = tmp
            sqmap = _square_title_by_pos(int(getattr(p, "id", 0) or 0))
            missing = []
            for pos in (line or []):
                try:
                    pos = int(pos)
                except Exception:
                    continue
                if pos == 12:
                    continue  # FREE
                raw = sqmap.get(pos, "") or ""
                nt = _norm_title(raw)
                if not nt:
                    missing.append(raw or f"pos {pos}")
                    continue
                hit = False
                for pt in played:
                    if not pt:
                        continue
                    # match if either contains the other (handles remaster / extra words)
                    if (pt.find(nt) != -1) or (nt.find(pt) != -1):
                        hit = True
                        break
                if not hit:
                    missing.append(raw or f"pos {pos}")
            if missing:
                auto_valid = False
                detail = f"Bingo line not yet played: missing={missing} mk={_mk_sig(mk)}"
        except Exception:
            # Fail closed: do NOT auto-accept if validation errors.
            auto_valid = False
            detail = f"Bingo validation error mk={_mk_sig(mk)}"


    # SOLO: first valid bingo ends the game immediately.
    if (getattr(g, "game_type", None) or "") == "solo":
        with best_effort():
            if (getattr(g, "status", None) or "") == "ended":
                return JSONResponse({"ok": True, "already_ended": True, "auto_valid": False})
        if not auto_valid:
            return JSONResponse({"ok": True, "auto_valid": False, "detail": detail, "claim_round": current_round})
        c = models.BingoClaim(game_id=g.id, player_id=p.id, auto_valid=True, status="accepted", detail=detail, pattern=pattern)
        with best_effort():
            g.status = "ended"
    else:
        c = models.BingoClaim(game_id=g.id, player_id=p.id, auto_valid=auto_valid, status="pending", detail=detail, pattern=pattern)



    c.claim_round = current_round

    db.add(c)
    db.commit()
    claim_id = getattr(c, "id", None)

    with best_effort():
        await hub.broadcast_host(code_u, {"type": "claims_updated"})
        await hub.broadcast_players(code_u, {"type": "claims_updated"})

    status_val = ''
    try:
        status_val = (getattr(c, 'status', '') or '')
    except Exception:
        status_val = ''
    if not status_val:
        # Hosted games should default to pending; solo can be accepted when auto_valid.
        try:
            is_solo = (getattr(g, 'game_type', None) or '') == 'solo'
        except Exception:
            is_solo = False
        status_val = 'accepted' if (is_solo and auto_valid) else 'pending'
    __payload = {"ok": True, "claim_id": claim_id, "status": status_val, "auto_valid": auto_valid, "detail": detail, "claim_round": current_round}
    with best_effort():
        if isinstance(__solo_debug, dict) and __solo_debug:
            __payload.update(__solo_debug)
    return JSONResponse(__payload)


@router.get('/game/{code}/winners.json')
def game_winners(code: str, request: Request, db: Session = Depends(get_db)):
    """Who has won so far, for the players of this game (their per-game cookie is the key)."""
    code_u = _upper_code(_norm_code(code))
    g = db.query(models.Game).filter(models.Game.code == code_u).first()
    if not g or not _player_from_cookie(request, db, g):
        return JSONResponse({'error': 'not_authorized'}, status_code=403)
    return JSONResponse(scoreboard(db, g))


@router.get('/game/{code}/last_track_state')
async def game_last_track_state(code: str):
    """Return last cached WS 'track' payload for this game code, or {}."""
    code_u = _upper_code(_norm_code(code))
    with best_effort():
        v = LAST_TRACK_STATE.get(code_u)
        if isinstance(v, dict):
            return JSONResponse(v)
    return JSONResponse({})


@router.websocket('/ws/game/{code}')
async def ws_player_game(websocket: WebSocket, code: str):
    code_u = _upper_code(code)

    # Only a player who joined this game (their per-game cookie matches a player in it) may listen in
    db = SessionLocal()
    try:
        g0 = db.query(models.Game).filter(models.Game.code == code_u).first()
        joined = bool(g0 and _player_from_cookie(websocket, db, g0))
    except Exception:
        joined = False
    finally:
        db.close()
    if not joined:
        await websocket.close(code=1008)
        return

    await hub.connect_player(code_u, websocket)
    

    # Send current game state (including continue_seq) so reconnects can clear stale accepted locks.
    db = None
    try:
        db = SessionLocal()
        g = db.query(models.Game).filter(models.Game.code == code_u).first()
        if g:
            await websocket.send_json({"type": "game_state", "status": getattr(g, 'status', ''), "continue_seq": int(getattr(g, 'continue_seq', 0) or 0)})
    except Exception:
        pass
    finally:
        with best_effort():
            if db is not None:
                db.close()

    # Immediately send last known track state (if any) so refresh-before-10s can still reveal on time.
    with best_effort():
        _last = LAST_TRACK_STATE.get(code_u)
        if isinstance(_last, dict) and _last.get('type') == 'track':
            await websocket.send_json(_last)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        await hub.disconnect_player(code_u, websocket)
