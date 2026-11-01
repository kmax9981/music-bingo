"""Play Alone: start a session, mark squares, record songs."""
import uuid
import re
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy.orm import Session
from ..db import get_db
from .. import models, spotify
from ..util import gen_code
from ..cards import _ensure_card_squares
from ..common import _host_user_from_session, _norm_code, _owner_key_for_user, _player_cookie_name, _upper_code, require_host, set_cookie, templates
from ..playlists import SPOTIFY_MADE_PLAYLIST_ERROR, _fill_missing_explicit, _parse_playlist_ref, _playlist_error_text, _spotify_made_error, _visible_playlist, _visible_playlists
from ..errors import best_effort, rollback_quietly, log_swallowed

router = APIRouter()


@router.get("/play", response_class=HTMLResponse)
def play_page(request: Request, db: Session = Depends(get_db)):
    u = None
    try:
        u = _host_user_from_session(request, db)
    except Exception:
        u = None
    if not u:
        return RedirectResponse(url="/login?next=/play", status_code=302)
    held = require_host(request)   # a host still on a temporary password is held at the Account page
    if held:
        return held
    with best_effort():
        if getattr(u, "role", "host") == "player":
            return HTMLResponse("Forbidden", status_code=403)

    uid = int(getattr(u, "id", 0) or 0) or None
    saved_playlists = []
    try:
        saved_playlists = _visible_playlists(db, uid).all()
        _fill_missing_explicit(db, saved_playlists, uid)
    except Exception:
        saved_playlists = []
    spotify_connected = bool(spotify.get_valid_access_token(db, host_user_id=uid))
    owner_key = _owner_key_for_user(u)
    recent_solo_games = db.query(models.Game)\
        .filter(models.Game.owner_key == owner_key, models.Game.game_type == 'solo')\
        .order_by(models.Game.created_at.desc())\
        .limit(50).all()


    return templates.TemplateResponse(request, "play.html", {
        "request": request,
        "user": u,
        "saved_playlists": saved_playlists,
        "spotify_connected": spotify_connected,
        "recent_solo_games": recent_solo_games,
    })


def _play_page_error(request, db, u, msg, status_code=400):
    """Re-render the solo start page with an error, with the same context as GET /play."""
    uid = int(getattr(u, "id", 0) or 0) or None
    return templates.TemplateResponse(request, "play.html", {
        "request": request,
        "user": u,
        "saved_playlists": _visible_playlists(db, uid).all(),
        "spotify_connected": bool(uid and spotify.get_valid_access_token(db, host_user_id=uid)),
        "recent_solo_games": db.query(models.Game)
            .filter(models.Game.owner_key == _owner_key_for_user(u), models.Game.game_type == 'solo')
            .order_by(models.Game.created_at.desc()).limit(50).all(),
        "error": msg,
    }, status_code=status_code)


# 
@router.post("/play/solo/{code}/delete")
def delete_solo_game(code: str, request: Request, db: Session = Depends(get_db)):
    r = require_host(request, next_path=request.url.path)
    if r:
        return r
    u = _host_user_from_session(request, db)
    owner_key = _owner_key_for_user(u)
    code_u = _upper_code(_norm_code((code or "").upper()))
    g = (db.query(models.Game)
            .filter(models.Game.code == code_u,
                    models.Game.owner_key == owner_key,
                    models.Game.game_type == 'solo')
            .first())
    if not g:
        return RedirectResponse(url="/play", status_code=302)

    try:
        db.delete(g)
        db.commit()
    except Exception:
        db.rollback()
        return RedirectResponse(url="/play?err=delete_failed", status_code=302)

    return RedirectResponse(url="/play", status_code=302)


@router.get("/play/solo/{code}/{playerno}", response_class=HTMLResponse)
def play_solo(code: str, playerno: int, request: Request, db: Session = Depends(get_db)):
    # Solo play: renders a 5x5 bingo card and embeds Spotify playback using the host user's token.
    r = require_host(request, next_path=request.url.path)
    if r:
        return r

    u = None
    try:
        u = _host_user_from_session(request, db)
    except Exception:
        u = None
    if not u:
        return RedirectResponse(url="/login?next=/play", status_code=302)

    owner_key = _owner_key_for_user(u)

    code_u = _upper_code(_norm_code(code))
    g = db.query(models.Game).filter(models.Game.code == code_u, models.Game.owner_key == owner_key, models.Game.game_type == 'solo').first()
    if not g:
        return RedirectResponse(url="/play", status_code=302)

    p = db.query(models.Player).filter(models.Player.game_id == g.id, models.Player.number == int(playerno)).first()
    if not p:
        return RedirectResponse(url="/play", status_code=302)


    # Solo games have no host-admit step; ensure player is admitted.
    try:
        if not getattr(p, 'admitted', False):
            p.admitted = True
            db.commit()
    except Exception:
        rollback_quietly(db)
    uid = int(getattr(u, "id", 0) or 0) or None
    token = spotify.get_valid_access_token(db, host_user_id=uid)
    if not token:
        return RedirectResponse(url="/host/spotify/connect", status_code=302)

    # Playlist name (best effort)
    pl_name = "Solo Playlist"
    with best_effort():
        sp = db.query(models.SavedPlaylist).filter(models.SavedPlaylist.spotify_playlist_id == g.spotify_playlist_id).first()
        if sp and getattr(sp, "name", None):
            pl_name = sp.name
        else:
            with best_effort():
                meta = spotify.api_get(db, f"/playlists/{g.spotify_playlist_id}", params={"market": "US"}, host_user_id=uid)
                if meta and isinstance(meta, dict) and meta.get("name"):
                    pl_name = meta.get("name")

    # Build 5x5 grid from CardSquare.pos (0..24) + marked.
    card_grid = [[{"title": "", "artist": "", "marked": False} for _ in range(5)] for __ in range(5)]
    try:
        squares = db.query(models.CardSquare).filter(models.CardSquare.player_id == p.id).all()
    except Exception:
        squares = []

    by_pos = {}
    for sq in (squares or []):
        try:
            pos = int(getattr(sq, "pos", -1))
        except Exception:
            pos = -1
        if 0 <= pos <= 24:
            by_pos[pos] = sq

    for pos in range(25):
        r_i = pos // 5
        c_i = pos % 5
        sq = by_pos.get(pos)
        if sq is None:
            continue
        title = (getattr(sq, "title", "") or "")
        marked = bool(getattr(sq, "marked", False))
        is_free = bool(getattr(sq, "is_free", False))
        if is_free or pos == 12:
            title = "FREE" if not title.strip() else title
            marked = True
        card_grid[r_i][c_i] = {"title": title, "artist": "", "marked": bool(marked)}

    # Ensure center is FREE+marked even if DB is missing it
    card_grid[2][2] = {"title": "FREE", "artist": "", "marked": True}

    resp = templates.TemplateResponse(request, "play_solo.html", {
        "request": request,
        "card_grid": card_grid,
        "code": code_u,
        "playerno": int(playerno),
        "player_name": getattr(p, "name", "Player"),
        "playlist_name": pl_name,
        "spotify_playlist_id": g.spotify_playlist_id,
        "access_token": token,
      "game_status": (getattr(g, "status", "") or ""),
      "game_ended": ((getattr(g, "status", "") or "") == "ended"),
    })
    # SOLO: set the per-game player cookie used by /player/{code}/{playerno}/claim_bingo
    with best_effort():
        set_cookie(request, resp, _player_cookie_name(code_u), getattr(p, "token", "") or "")
    return resp


@router.post("/play/start")
def play_start(  # sync on purpose: blocking Spotify calls run in FastAPI's threadpool
    request: Request,
    db: Session = Depends(get_db),
    playlist: str = Form(""),
    saved_playlist_id: str = Form(""),
):
    r = require_host(request)
    if r:
        return r
    u = _host_user_from_session(request, db)
    # Solo games may run without a logged-in host; default owner_key to ''
    # If a host user is present, reuse their derived owner_key.
    owner_key = ''
    try:
        u = locals().get('u')
        if u:
            owner_key = _owner_key_for_user(u)
    except Exception:
        owner_key = ''

    if not u:
        return RedirectResponse(url="/login?next=/play", status_code=302)

    uid = int(u.id) if u else None

    # Solo games always use the player's own Spotify login, like hosted games. (They used to borrow the
    # token of whoever saved the playlist, which failed whenever that account had never connected Spotify.)
    if not spotify.get_valid_access_token(db, host_user_id=uid):
        return RedirectResponse(url="/host/spotify/connect", status_code=302)

    # Resolve playlist id either from pasted URL/ID or from saved selection
    raw = (playlist or "").strip()
    spotify_playlist_id = ""
    playlist_name = ""
    if raw:
        v = raw
        spotify_playlist_id = _parse_playlist_ref(v) or v.strip()
        if _spotify_made_error(spotify_playlist_id):
            return _play_page_error(request, db, u, SPOTIFY_MADE_PLAYLIST_ERROR, 400)

        # Best-effort: fetch playlist name from Spotify for nicer UI
        with best_effort():
            meta = spotify.api_get(db, f"/playlists/{spotify_playlist_id}", params={"market": "US"}, host_user_id=uid)
            if meta and isinstance(meta, dict) and meta.get("name"):
                playlist_name = meta.get("name")
    else:
        spid = (saved_playlist_id or "").strip()
        if spid:
            pl = _visible_playlist(db, uid, spid)  # someone else's private playlist counts as not found
            if not pl:
                return _play_page_error(request, db, u, "Saved playlist not found.", 400)
            spotify_playlist_id = pl.spotify_playlist_id
            playlist_name = getattr(pl, "name", "") or ""

        else:
            return _play_page_error(request, db, u, "Please paste a playlist link/ID or choose a saved playlist.", 400)

    # Fallback label if we couldn't fetch anything
    if not playlist_name:
        playlist_name = "Solo Playlist"

    # Use logged-in host username for the solo player name (no extra input needed)
    nm = (getattr(u, "username", None) or getattr(u, "display_name", None) or "Host").strip()[:40]

    code = gen_code(5)
    tries = 0
    while db.query(models.Game).filter(models.Game.code == code).first():
        tries += 1
        if tries > 20:
            return _play_page_error(request, db, u, "Could not generate unique game code. Try again.", 500)
        code = gen_code(5)

    g = models.Game(code=code, name=f"Solo: {playlist_name}"[:120], spotify_playlist_id=spotify_playlist_id, status="started", owner_key=owner_key, game_type="solo")
    db.add(g)
    db.flush()

    token = uuid.uuid4().hex
    p = models.Player(game_id=g.id, number=1, name=nm, admitted=True, token=token)
    db.add(p)
    db.flush()

    try:
        _ensure_card_squares(db, g, p, host_user_id=uid)
    except Exception as e:
        db.rollback()
        return _play_page_error(request, db, u, _playlist_error_text(e))

    db.commit()

    resp = RedirectResponse(url=f"/play/solo/{code}/1", status_code=302)
    resp.set_cookie(_player_cookie_name(code), token, max_age=60*60*24*30, httponly=True, samesite="lax")
    return resp


# SOLO client reports a track as "played" so server-side bingo validation can match DB PlayedTrack rows.
# This is intentionally small + best-effort (client can fail silently).
@router.post("/player/{code}/{playerno}/played_track")
async def solo_played_track(code: str, playerno: int, request: Request, db: Session = Depends(get_db)):
    """SOLO client reports a track as "played".

    Writes a PlayedTrack row so server-side bingo validation can match against played_tracks.
    Best-effort: returns JSON {ok: bool, ...}.

    Payload may include: {title, artist, uri}.
    """
    # Normalize code
    code_u = _norm_code(code)

    # Ensure game exists
    g = None
    try:
        g = db.query(models.Game).filter(models.Game.code == code_u).first()
    except Exception:
        g = None
    if not g:
        return JSONResponse({"ok": False, "error": "game not found"}, status_code=404)

    # Only solo games use this endpoint, and only their owner may record played songs
    # (same ownership check as claim_bingo). Hosted games record songs through the host's own routes.
    if (getattr(g, "game_type", None) or "") != "solo":
        return JSONResponse({"ok": False, "error": "forbidden"}, status_code=403)
    try:
        _u = _host_user_from_session(request, db)
    except Exception:
        _u = None
    if not _u or (getattr(g, "owner_key", None) or "") != _owner_key_for_user(_u):
        return JSONResponse({"ok": False, "error": "forbidden"}, status_code=403)

    # Verify player belongs to this game
    p = None
    try:
        # players table uses Player.number (NOT player_no)
        p = (db.query(models.Player)
              .filter(models.Player.game_id == g.id, models.Player.number == int(playerno))
              .first())
    except Exception:
        p = None
    if not p:
        return JSONResponse({"ok": False, "error": "player not found"}, status_code=404)

    # Parse payload
    try:
        body = await request.json()
        if not isinstance(body, dict):
            body = {}
    except Exception:
        body = {}

    # ---- robust payload normalization (SOLO) ----
    # Client may send either:
    #   {title: str, artist: str, uri: str}
    # or a richer object like:
    #   {track: {name, uri, id, artists:[{name}]} }
    # or fields that are accidentally objects (leading to junk).
    def _safe_str(v):
        try:
            if v is None:
                return ""
            if isinstance(v, (int, float, bool)):
                return str(v)
            if isinstance(v, str):
                return v
            # dict/list/etc -> don't stringify blindly
            return ""
        except Exception:
            return ""

    def _artist_from_track_obj(t):
        with best_effort():
            arts = t.get("artists")
            if isinstance(arts, list) and arts:
                # main artist only ("Sweet Dreams" lists three; the hosted page shows just the first too)
                for a in arts:
                    if isinstance(a, dict) and a.get("name"):
                        return str(a.get("name"))[:200]
                return ""
        return ""

    track_obj = body.get("track") if isinstance(body, dict) else None
    if isinstance(track_obj, dict):
        if not body.get("title") and track_obj.get("name"):
            body["title"] = track_obj.get("name")
        if not body.get("uri") and track_obj.get("uri"):
            body["uri"] = track_obj.get("uri")
        if not body.get("track_id") and track_obj.get("id"):
            body["track_id"] = track_obj.get("id")
        if not body.get("artist"):
            a = _artist_from_track_obj(track_obj)
            if a:
                body["artist"] = a

    title_s = _safe_str(body.get("title") if isinstance(body, dict) else "")
    artist_s = _safe_str(body.get("artist") if isinstance(body, dict) else "")
    uri_s = _safe_str(body.get("uri") if isinstance(body, dict) else "")

    # Ignore obvious junk
    bad = {"[object object]", "[object Object]", "object object"}
    if title_s.strip().lower() in bad:
        title_s = ""
    if uri_s.strip().lower() in bad:
        uri_s = ""
    # ---- /robust payload normalization (SOLO) ----

    # Derive spotify_track_id from uri when possible
    track_id = ""
    if uri_s:
        try:
            if uri_s.startswith("spotify:track:"):
                track_id = uri_s.split("spotify:track:", 1)[1].strip()
            else:
                # URLs like https://open.spotify.com/track/<id>?...
                m = re.search(r"open\.spotify\.com/track/([A-Za-z0-9]+)", uri_s)
                if m:
                    track_id = m.group(1)
        except Exception:
            track_id = ""

    if not title_s and not track_id:
        return JSONResponse({"ok": False, "error": "missing title/track"}, status_code=400)

    # If we still don't have a track_id, try to use title as a stable-ish key.
    # (Bingo validation will primarily use title matching too.)
    key = (track_id or title_s).strip().lower()

    # De-dupe within game
    with best_effort():
        if track_id:
            already = (db.query(models.PlayedTrack)
                        .filter(models.PlayedTrack.game_id == g.id, models.PlayedTrack.spotify_track_id == track_id)
                        .first())
            if already:
                return JSONResponse({"ok": True, "deduped": True})

    # Compute next seq
    next_seq = 1
    try:
        last = (db.query(models.PlayedTrack)
                .filter(models.PlayedTrack.game_id == g.id)
                .order_by(models.PlayedTrack.seq.desc())
                .first())
        if last and getattr(last, 'seq', None) is not None:
            next_seq = int(last.seq) + 1
    except Exception:
        next_seq = 1

    # Insert played track (schema-required fields)
    try:
        pt = models.PlayedTrack(
            game_id=g.id,
            seq=int(next_seq),
            spotify_track_id=(track_id or key)[:128],
            title=(title_s or "")[0:200] or "(unknown)",
            artist=(artist_s or "")[0:200] or "",
        )
        db.add(pt)
        db.commit()
    except Exception:
        rollback_quietly(db)
        # Keep error minimal; detailed traceback stays in logs
        return JSONResponse({"ok": False, "error": "db write failed"}, status_code=500)

    return JSONResponse({"ok": True, "seq": int(next_seq)})


@router.get("/player/{code}/{playerno}/played_tracks")
def solo_played_tracks(code: str, playerno: int, request: Request, db: Session = Depends(get_db)):
    """The songs recorded for a SOLO game, newest first, so the Played Tracks list can be rebuilt when the
    game is opened in a new tab or on another device. Only the solo game's owner may read it."""
    g = db.query(models.Game).filter(models.Game.code == _norm_code(code)).first()
    if not g or (getattr(g, "game_type", None) or "") != "solo":
        return JSONResponse({"ok": False, "error": "forbidden"}, status_code=403)
    try:
        u = _host_user_from_session(request, db)
    except Exception:
        u = None
    if not u or (getattr(g, "owner_key", None) or "") != _owner_key_for_user(u):
        return JSONResponse({"ok": False, "error": "forbidden"}, status_code=403)
    rows = (db.query(models.PlayedTrack).filter(models.PlayedTrack.game_id == g.id)
              .order_by(models.PlayedTrack.seq.desc()).limit(50).all())
    return JSONResponse({"ok": True, "tracks": [{"title": r.title or "", "artist": r.artist or ""} for r in rows]})


@router.post("/play/solo/{code}/{playerno}/toggle")
async def solo_toggle_square(code: str, playerno: int, request: Request, db: Session = Depends(get_db)):
    # Toggle (dab/undab) a single square for SOLO play.
    # Accepts JSON {"row":..,"col":..} OR form row=.. col=..
    # Uses CardSquare.pos (0..24) and CardSquare.marked.

    try:
        rr = require_host(request, next_path=request.url.path)
        if rr:
            return JSONResponse({"ok": False, "error": "forbidden"}, status_code=403)
    except Exception:
        return JSONResponse({"ok": False, "error": "forbidden"}, status_code=403)

    u = None
    try:
        u = _host_user_from_session(request, db)
    except Exception:
        u = None
    if not u:
        return JSONResponse({"ok": False, "error": "not_logged_in"}, status_code=401)

    code_u = _upper_code(_norm_code(code))
    g = db.query(models.Game).filter(models.Game.code == code_u).first()
    if not g:
        return JSONResponse({"ok": False, "error": "game_not_found"}, status_code=404)

    p = db.query(models.Player).filter(models.Player.game_id == g.id, models.Player.number == int(playerno)).first()
    if not p:
        return JSONResponse({"ok": False, "error": "player_not_found"}, status_code=404)

    row = None
    col = None

    with best_effort():
        ctype = (request.headers.get("content-type") or "").lower()
        if ctype.startswith("application/json"):
            data = await request.json()
            if isinstance(data, dict):
                row = data.get("row", data.get("r"))
                col = data.get("col", data.get("c"))

    if row is None or col is None:
        with best_effort():
            form = await request.form()
            row = row if row is not None else form.get("row", form.get("r"))
            col = col if col is not None else form.get("col", form.get("c"))

    try:
        ri = int(row)
        ci = int(col)
    except Exception:
        return JSONResponse({"ok": False, "error": "bad_coords"}, status_code=400)

    if not (0 <= ri < 5 and 0 <= ci < 5):
        return JSONResponse({"ok": False, "error": "out_of_range"}, status_code=400)

    pos = (ri * 5) + ci

    if pos == 12:
        return JSONResponse({"ok": True, "row": ri, "col": ci, "marked": True})

    sq = db.query(models.CardSquare).filter(
        models.CardSquare.player_id == p.id,
        models.CardSquare.pos == pos,
    ).first()
    if not sq:
        return JSONResponse({"ok": False, "error": "square_not_found"}, status_code=404)

    with best_effort():
        if bool(getattr(sq, "is_free", False)):
            sq.marked = True
            db.add(sq)
            db.commit()
            return JSONResponse({"ok": True, "row": ri, "col": ci, "marked": True})

    try:
        if not hasattr(sq, "marked"):
            return JSONResponse({"ok": False, "error": "no_marked_column"}, status_code=500)
        sq.marked = not bool(getattr(sq, "marked", False))
        marked_now = bool(sq.marked)
        db.add(sq)
        db.commit()
    except Exception as e:
        rollback_quietly(db)
        log_swallowed(e)   # the details go to the log, not to the browser
        return JSONResponse({"ok": False, "error": "db_error"}, status_code=500)

    return JSONResponse({"ok": True, "row": ri, "col": ci, "marked": marked_now})
