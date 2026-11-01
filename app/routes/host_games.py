"""Host: dashboard, creating/saving/renaming/resetting/deleting games, events."""
import sqlalchemy as sa
from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from starlette.responses import Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy.orm import Session
from ..db import get_db
from .. import models, spotify, themes, settings
from ..ws import hub
from ..util import clean_title_for_card, gen_code, normalize_key
from typing import Optional
from urllib.parse import quote, unquote
from ..common import __host_err_redirect, _back_to, _host_uid, _host_user_from_session, _owned_game, _owner_key_for_user, require_host, templates
from ..cleanup import delete_game
from ..cards import pattern_key
from ..paper import PAPER_DEFAULT_CARDS, PAPER_MAX_CARDS, _LOGO_MAX_BYTES, _create_paper_cards, _host_event, _event_json
from ..playlists import SPOTIFY_MADE_PLAYLIST_ERROR, _fill_missing_explicit, _parse_playlist_ref, _playlist_error_text, _spotify_made_error, _visible_playlist, _visible_playlists
from ..state import LAST_TRACK_STATE, _PLAY_RESTARTED_AT
from ..errors import best_effort

router = APIRouter()


@router.post('/host/game/{code}/save')
def host_save_game(request: Request, code: str, db: Session = Depends(get_db), saved: str = Form('1'), next: str = Form('')):
    """Save a game (keep it, with its paper cards, on the Saved Games page) or take it off that page again."""
    r = require_host(request)
    if r:
        return r
    g = _owned_game(request, db, code)
    if not g or g.game_type != 'hosted':
        return RedirectResponse(url='/host', status_code=302)
    g.is_saved = (saved == '1')
    db.commit()
    return RedirectResponse(url=_back_to(next, f'/host/game/{g.code}'), status_code=302)


@router.post('/host/game/{code}/rename')
def host_rename_game(request: Request, code: str, db: Session = Depends(get_db), name: str = Form(''), next: str = Form('')):
    r = require_host(request)
    if r:
        return r
    g = _owned_game(request, db, code)
    nm = (name or '').strip()[:120]
    if g and nm:
        g.name = nm   # also the title on printed paper cards
        db.commit()
    return RedirectResponse(url=_back_to(next, '/host/saved'), status_code=302)


@router.get('/host/saved', response_class=HTMLResponse)
def host_saved_games(request: Request, db: Session = Depends(get_db)):
    r = require_host(request, next_path='/host/saved')
    if r:
        return r
    u = _host_user_from_session(request, db)
    games = (db.query(models.Game)
               .filter(models.Game.owner_key == _owner_key_for_user(u), models.Game.game_type == 'hosted', models.Game.is_saved == sa.true())
               .order_by(models.Game.last_played_at.desc().nullslast(), models.Game.created_at.desc()).all())
    gids = [g.id for g in games]
    paper = dict(db.query(models.Player.game_id, sa.func.count(models.Player.id))
                   .filter(models.Player.game_id.in_(gids), models.Player.is_paper == sa.true())
                   .group_by(models.Player.game_id).all()) if gids else {}
    events = _event_lookup(db, u.id)
    rows = [{'g': g, 'paper': paper.get(g.id, 0), 'event': events.get(g.event_id)} for g in games]
    return templates.TemplateResponse(request, 'host_saved_games.html', {'request': request, 'rows': rows})


def _event_lookup(db, uid):
    """This host's events by id as {'id', 'name', 'has_logo'} (without loading the logo images)."""
    return {vid: {'id': vid, 'name': name or '', 'has_logo': bool(has_logo)}
            for vid, name, has_logo in db.query(models.Event.id, models.Event.name, models.Event.logo.isnot(None)).filter(models.Event.host_user_id == int(uid)).all()}


HISTORY_LIMIT = 50


@router.get('/host/history', response_class=HTMLResponse)
def host_game_history(request: Request, db: Session = Depends(get_db)):
    """The host's most recent games (saved or not), newest first, with what you can do to each."""
    r = require_host(request, next_path='/host/history')
    if r:
        return r
    u = _host_user_from_session(request, db)
    games = (db.query(models.Game)
               .filter(models.Game.owner_key == _owner_key_for_user(u), models.Game.game_type == 'hosted')
               .order_by(models.Game.created_at.desc()).limit(HISTORY_LIMIT).all())
    gids = [g.id for g in games]
    paper, players = {}, {}
    if gids:
        for gid, is_paper, n in (db.query(models.Player.game_id, models.Player.is_paper, sa.func.count(models.Player.id))
                                   .filter(models.Player.game_id.in_(gids)).group_by(models.Player.game_id, models.Player.is_paper).all()):
            (paper if is_paper else players)[gid] = n
    events = _event_lookup(db, u.id)
    rows = [{'g': g, 'paper': paper.get(g.id, 0), 'players': players.get(g.id, 0), 'event': events.get(g.event_id)} for g in games]
    return templates.TemplateResponse(request, 'host_history.html', {'request': request, 'rows': rows, 'limit': HISTORY_LIMIT})


@router.post('/host/game/{code}/reset')
async def host_reset_game(request: Request, code: str, db: Session = Depends(get_db)):
    """"Play again": get this game ready for a new session and keep what makes it reusable: the game code,
    song list/playlist, event and every paper card (so printed cards, whose check codes depend on the game code,
    stay valid). Cleared: played songs, claims, rounds and phone players (they join again)."""
    r = require_host(request)
    if r:
        return r
    g = _owned_game(request, db, code)
    if not g:
        return RedirectResponse(url='/host', status_code=302)
    if (g.status or '').lower() != 'lobby':
        phone_ids = [pid for (pid,) in db.query(models.Player.id).filter(models.Player.game_id == g.id, models.Player.is_paper == sa.false()).all()]
        db.query(models.BingoClaim).filter(models.BingoClaim.game_id == g.id).delete(synchronize_session=False)
        if phone_ids:
            db.query(models.CardSquare).filter(models.CardSquare.player_id.in_(phone_ids)).delete(synchronize_session=False)
            db.query(models.Player).filter(models.Player.id.in_(phone_ids)).delete(synchronize_session=False)
        db.query(models.PlayedTrack).filter(models.PlayedTrack.game_id == g.id).delete(synchronize_session=False)
        g.status = 'lobby'
        g.started_at = None
        g.playback_started_at = None
        g.continue_seq = 0
        db.commit()
        LAST_TRACK_STATE.pop(g.code, None)
        _PLAY_RESTARTED_AT.pop(g.code, None)  # the first Play of the new session may restart the playlist again
        with best_effort():
            await hub.broadcast_players(g.code, {'type': 'game_reset'})   # phones go back to the join page
            await hub.broadcast_host(g.code, {'type': 'players_updated'})
    return RedirectResponse(url=f'/host/game/{g.code}?notice=' + quote('Ready for a new session. Same game code and paper cards; phone players need to join again.'), status_code=302)


@router.post('/host/game/{code}/delete')
def host_delete_game(request: Request, code: str, db: Session = Depends(get_db), from_saved: str = Form(''), next: str = Form('')):
    r = require_host(request)
    if r:
        return r

    g = _owned_game(request, db, code)
    if not g:
        return RedirectResponse(url='/host', status_code=302)
    if g.is_saved and not from_saved:
        return __host_err_redirect('That game is saved. Delete it from Saved Games, or remove it from saved first.')

    delete_game(db, g)   # the game with its players, cards, claims and history
    db.commit()
    return RedirectResponse(url=_back_to(next, '/host'), status_code=302)


@router.get('/host', response_class=HTMLResponse)
def host_dashboard(request: Request, db: Session = Depends(get_db)):
    r = require_host(request)
    if r:
        return r

    # If we were redirected here with a legacy ?error=... querystring, convert it to
    # a short-lived flash cookie and redirect again to /host so the URL stays clean.
    qerr = None
    try:
        qerr = request.query_params.get('error')
    except Exception:
        qerr = None
    if qerr:
        try:
            return __host_err_redirect(unquote(str(qerr)))
        except Exception:
            return __host_err_redirect(str(qerr))

    # Read flash error (set by /host/create_game)
    error = None
    flash = None
    try:
        flash = request.cookies.get('host_flash')
    except Exception:
        flash = None
    if flash:
        try:
            error = unquote(str(flash))
        except Exception:
            error = str(flash)

    u = _host_user_from_session(request, db)
    if not u:
        return RedirectResponse(url="/login?next=/host", status_code=302)
    uid = int(u.id) if u else None
    owner_key = _owner_key_for_user(u)
    saved_count = db.query(sa.func.count(models.Game.id)).filter(models.Game.owner_key == owner_key, models.Game.game_type == 'hosted',
                                                                  models.Game.is_saved == sa.true()).scalar() or 0
    playlists = _visible_playlists(db, uid).all()
    _fill_missing_explicit(db, playlists, uid)
    spotify_connected = bool(uid and spotify.get_valid_access_token(db, host_user_id=uid))

    resp = templates.TemplateResponse(request, 'host_dashboard.html', {
        'saved_count': saved_count,
        'my_theme_name': themes.theme_label(themes.theme_for_user_id(uid)),
        'request': request,
        'public_base': settings.public_base(),
        'playlists': playlists,
        'events': [_event_json(v) for v in db.query(models.Event).filter(models.Event.host_user_id == uid).order_by(models.Event.created_at.desc()).all()],
        'spotify_connected': spotify_connected,
        'error': error,
    })
    # Clear flash cookie after reading
    if flash:
        with best_effort():
            resp.delete_cookie('host_flash', path='/')
    return resp


@router.post('/host/create_game')
def host_create_game(
    request: Request,
    db: Session = Depends(get_db),
    game_name: str = Form(...),
    playlist_mode: str = Form(...),
    playlist_id_or_url: str = Form(''),
    saved_playlist_id: str = Form(''),
    paper_cards: str = Form(''),
    paper_count: str = Form(''),
    event_id: str = Form(''),
    win_pattern: str = Form(''),
    paper_join_footer: str = Form(''),
    paper_theme: str = Form(''),
):
    r = require_host(request)
    if r:
        return r

    spotify_playlist_id = ''
    if playlist_mode == 'saved':
        try:
            pid = int(saved_playlist_id)
        except Exception:
            return __host_err_redirect('Select a saved playlist (or paste a playlist link).')
        _u = _host_user_from_session(request, db)
        pl = _visible_playlist(db, int(_u.id) if _u else None, pid)  # someone else's private one counts as not found
        if not pl:
            return __host_err_redirect('Saved playlist not found. Please select again.')
        spotify_playlist_id = pl.spotify_playlist_id
    else:
        v = (playlist_id_or_url or '').strip()
        if not v:
            return __host_err_redirect('Paste a Spotify playlist link or ID (or select a saved playlist).')
        spotify_playlist_id = _parse_playlist_ref(v)
        if not spotify_playlist_id:
            return __host_err_redirect("That doesn't look like a Spotify playlist link. In Spotify use Share → Copy link to playlist.")
        if _spotify_made_error(spotify_playlist_id):
            return __host_err_redirect(SPOTIFY_MADE_PLAYLIST_ERROR)

    u = _host_user_from_session(request, db)

    owner_key = _owner_key_for_user(u)
    uid = int(u.id) if u else None

    if not (uid and spotify.get_valid_access_token(db, host_user_id=uid)):
        return RedirectResponse(url='/host/spotify/connect', status_code=302)

    try:
        items = []
        offset = 0
        while True:
            data = spotify.api_get(db, f'/playlists/{spotify_playlist_id}/tracks', params={'limit': 100, 'offset': offset}, host_user_id=uid)
            batch = data.get('items', [])
            items.extend(batch)
            if len(batch) < 100:
                break
            offset += 100
    except Exception as e:
        return __host_err_redirect(_playlist_error_text(e))

    titles = []
    for it in items:
        tr = (it or {}).get('track') or {}
        if not tr or tr.get('is_local'):
            continue
        if tr.get('type') != 'track':
            continue
        name = tr.get('name') or ''
        ct = clean_title_for_card(name)
        if ct:
            titles.append(ct)

    seen = set()
    uniq = []
    for t in titles:
        k = normalize_key(t)
        if k in seen:
            continue
        seen.add(k)
        uniq.append(t)

    if len(uniq) < 24:
        return __host_err_redirect(f'That playlist has only {len(uniq)} different songs. A game needs at least 24; around 75 or fewer works best.')

    code = gen_code(5)
    tries = 0
    while db.query(models.Game).filter(models.Game.code == code).first():
        tries += 1
        if tries > 20:
            return __host_err_redirect('Failed to generate unique game code. Please try again.')
        code = gen_code(5)

    g = models.Game(code=code, name=(game_name or 'Bingo Game').strip(), spotify_playlist_id=spotify_playlist_id, status='lobby', owner_key=owner_key, game_type='hosted', win_pattern=pattern_key(win_pattern))
    db.add(g)
    db.commit()

    # The event (its logo or name in the center square) is for every game, phone cards and paper cards alike
    chosen = (event_id or '').strip()
    event = _host_event(db, uid, chosen) if chosen else None
    g.event_id = event.id if event else None
    db.commit()

    # Paper cards chosen: remember the footer choice and theme, make the cards and open the print page
    if paper_cards:
        g.paper_join_footer = bool(paper_join_footer)
        # "Use my theme's colors": remember which theme (a later theme change must not recolor cards already printed)
        g.paper_theme = themes.theme_for_user_id(uid) if paper_theme else ''
        db.commit()
        try:
            n = int(paper_count)
        except Exception:
            n = PAPER_DEFAULT_CARDS
        try:
            made = _create_paper_cards(db, g, max(1, min(n, PAPER_MAX_CARDS)))
        except Exception as e:
            db.rollback()
            print(f'PAPER_CARDS_FAILED game={code}: {e!r}')
            made = []
        if made:
            return RedirectResponse(url=f'/host/game/{code}/paper', status_code=302)

    return RedirectResponse(url=f'/host/game/{code}', status_code=302)


@router.get('/host/events')
def host_events_list(request: Request, db: Session = Depends(get_db)):
    r = require_host(request)
    if r:
        return JSONResponse({'error': 'login required'}, status_code=401)
    uid = _host_uid(request, db)
    vs = db.query(models.Event).filter(models.Event.host_user_id == uid).order_by(models.Event.created_at.desc()).all()
    return JSONResponse({'events': [_event_json(v) for v in vs]})


async def _read_logo(logo):
    """An uploaded logo -> (bytes, mime, error message). No file -> (None, None, None)."""
    if logo is None or not getattr(logo, 'filename', ''):
        return None, None, None
    data = await logo.read(_LOGO_MAX_BYTES + 1)
    if len(data) > _LOGO_MAX_BYTES:
        return None, None, 'That logo is too large. Use a PNG or JPG under 5 MB.'
    if data.startswith(b'\x89PNG\r\n\x1a\n'):
        return data, 'image/png', None
    if data.startswith(b'\xff\xd8\xff'):
        return data, 'image/jpeg', None
    return None, None, 'The logo must be a PNG or JPG image.'


@router.post('/host/events')
async def host_events_add(request: Request, db: Session = Depends(get_db), name: str = Form(''),
                          logo: Optional[UploadFile] = File(None)):
    r = require_host(request)
    if r:
        return JSONResponse({'error': 'login required'}, status_code=401)
    uid = _host_uid(request, db)
    nm = (name or '').strip()[:80]
    data, mime, err = await _read_logo(logo)
    if err:
        return JSONResponse({'error': err}, status_code=400)
    if not nm:
        return JSONResponse({'error': 'Type the event name. It is required (the logo is optional).'}, status_code=400)
    v = models.Event(host_user_id=uid, name=nm, logo=data, logo_mime=mime)
    db.add(v)
    db.commit()
    return JSONResponse({'ok': True, 'event': _event_json(v)})


@router.get('/host/events/manage', response_class=HTMLResponse)
def host_events_page(request: Request, db: Session = Depends(get_db)):
    """Options > Events: the events saved for paper cards (name and/or logo for the center square)."""
    r = require_host(request)
    if r:
        return r
    uid = _host_uid(request, db)
    vs = db.query(models.Event).filter(models.Event.host_user_id == uid).order_by(models.Event.created_at.desc()).all()
    return templates.TemplateResponse(request, 'host_events.html', {'request': request, 'events': [_event_json(v) for v in vs]})


@router.post('/host/events/{event_id}/logo')
async def host_events_set_logo(request: Request, event_id: int, db: Session = Depends(get_db),
                               logo: Optional[UploadFile] = File(None), remove: str = Form('')):
    """Replace an event's logo (or take it away with remove=1; the name is shown in the center square instead)."""
    r = require_host(request)
    if r:
        return JSONResponse({'error': 'login required'}, status_code=401)
    v = _host_event(db, _host_uid(request, db), event_id)
    if not v:
        return JSONResponse({'error': 'Event not found.'}, status_code=404)
    if remove:
        v.logo, v.logo_mime = None, None
    else:
        data, mime, err = await _read_logo(logo)
        if err or not data:
            return JSONResponse({'error': err or 'Choose a PNG or JPG image.'}, status_code=400)
        v.logo, v.logo_mime = data, mime
    db.commit()
    return JSONResponse({'ok': True, 'event': _event_json(v)})


@router.post('/host/events/{event_id}/rename')
def host_events_rename(request: Request, event_id: int, db: Session = Depends(get_db), name: str = Form('')):
    r = require_host(request)
    if r:
        return JSONResponse({'error': 'login required'}, status_code=401)
    v = _host_event(db, _host_uid(request, db), event_id)
    if not v:
        return JSONResponse({'error': 'Event not found.'}, status_code=404)
    v.name = (name or '').strip()[:80]
    if not v.name:
        return JSONResponse({'error': 'An event needs a name.'}, status_code=400)
    db.commit()
    return JSONResponse({'ok': True, 'event': _event_json(v)})


@router.post('/host/events/{event_id}/delete')
def host_events_delete(request: Request, event_id: int, db: Session = Depends(get_db)):
    r = require_host(request)
    if r:
        return JSONResponse({'error': 'login required'}, status_code=401)
    v = _host_event(db, _host_uid(request, db), event_id)
    if not v:
        return JSONResponse({'error': 'Event not found.'}, status_code=404)
    db.delete(v)  # games that used it simply print FREE from now on
    db.commit()
    return JSONResponse({'ok': True})


@router.get('/host/events/{event_id}/logo')
def host_events_logo(request: Request, event_id: int, db: Session = Depends(get_db)):
    r = require_host(request)
    if r:
        return Response(status_code=401)
    v = _host_event(db, _host_uid(request, db), event_id)
    if not v or not v.logo:
        return Response(status_code=404)
    return Response(content=v.logo, media_type=v.logo_mime or 'image/png', headers={'Cache-Control': 'private, max-age=3600'})
