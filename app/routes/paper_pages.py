"""Host: paper card pages (print, add, regenerate, check, claim, update)."""
import random
import uuid
import re
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy.orm import Session
from ..db import get_db
from .. import models, themes, settings
from ..cards import _PLAYLIST_TRACKS_CACHE, _card_line_sets, _ensure_card_squares
from ..claims import _announce_claim_decision
from ..common import __host_err_redirect, _current_round, _game_host_uid, _owned_game, require_host, templates
from ..cards import pattern_key
from ..paper import PAPER_DEFAULT_CARDS, PAPER_MAX_CARDS, _card_squares, _card_verdict, _create_paper_cards, _current_card_titles, _paper_card, _paper_cards, _paper_stale_report, _parse_paper_code, _played_keys, _event_json, paper_card_code, paper_display_title

router = APIRouter()


@router.get('/host/game/{code}/paper', response_class=HTMLResponse)
def host_paper_print(request: Request, code: str, db: Session = Depends(get_db)):
    r = require_host(request, next_path=f'/host/game/{code}/paper')
    if r:
        return r
    g = _owned_game(request, db, code)
    if not g:
        return RedirectResponse(url='/host', status_code=302)
    cards = _paper_cards(db, g)
    try:
        first = int(request.query_params.get('from') or 0)
    except Exception:
        first = 0
    if first:
        cards = [p for p in cards if (p.card_number or 0) >= first]
    only = request.query_params.get('cards') or ''
    chosen = {int(x) for x in re.findall(r'\d+', only)} if only else set()
    if chosen:
        cards = [p for p in cards if int(p.card_number or 0) in chosen]
    event = db.query(models.Event).filter(models.Event.id == g.event_id).first() if g.event_id else None
    # Size advice: few songs make cards alike (several winners on one song); say so, and if any cards had
    # to share a winning line
    all_cards = _paper_cards(db, g)
    layouts = [[None if sq.is_free else (sq.title or '').lower() for sq in _card_squares(db, p)] for p in all_cards]
    songs = len({t for lay in layouts for t in lay if t})
    seen_lines, shared = set(), 0
    for lay in layouts:
        ls = _card_line_sets(lay)
        shared += len(ls & seen_lines)
        seen_lines |= ls
    advice = None
    if shared:
        advice = (f'This playlist has only {songs} songs, so some cards share a winning line and could win on the same song. '
                  f'A playlist of 60 or more songs avoids that.')
    elif all_cards and songs < 60:
        advice = f'This playlist has {songs} songs, so cards are quite alike and several players may win close together. 60 or more songs works best.'
    return templates.TemplateResponse(request, 'paper_cards.html', {
        'advice': advice,
        'paper_theme': themes.valid_theme(g.paper_theme) if getattr(g, 'paper_theme', '') else '',   # a theme spec
        'my_theme_name': themes.theme_label(themes.theme_for_user_id(_game_host_uid(db, g))),
        'request': request,
        'game': g,
        'cards': [{'number': p.card_number, 'code': paper_card_code(g.code, p.card_number), 'squares': [{'is_free': sq.is_free, 'title': paper_display_title(sq.title)} for sq in _card_squares(db, p)]} for p in cards],
        'event': _event_json(event) if event else None,
        'join_url': f'{settings.public_base()}/game/{g.code}',
        'public_host': settings.public_base().split('://', 1)[-1],
        'public_base': settings.public_base(),
        'only_new': bool(first),
        'subset': ('updated' if chosen else ('new' if first else '')),
        'total_cards': len(all_cards),
        'new_cards': len(cards),
        'paper_max': PAPER_MAX_CARDS,
    })


@router.post('/host/game/{code}/paper/add')
def host_paper_add(request: Request, code: str, db: Session = Depends(get_db), count: str = Form('')):
    r = require_host(request)
    if r:
        return r
    g = _owned_game(request, db, code)
    if not g:
        return RedirectResponse(url='/host', status_code=302)
    try:
        n = int(count)
    except Exception:
        n = PAPER_DEFAULT_CARDS
    try:
        made = _create_paper_cards(db, g, max(1, n))
    except Exception as e:
        db.rollback()
        print(f'PAPER_CARDS_FAILED game={g.code}: {e!r}')
        return __host_err_redirect("Couldn't make the paper cards: the playlist couldn't be loaded from Spotify. Check Spotify is connected, then try again.")
    if not made:
        return __host_err_redirect(f'This game already has the maximum of {PAPER_MAX_CARDS} paper cards.')
    return RedirectResponse(url=f'/host/game/{g.code}/paper?from={made[0].card_number}', status_code=302)


@router.post('/host/game/{code}/paper/theme')
def host_paper_theme(request: Request, code: str, db: Session = Depends(get_db), mode: str = Form('plain')):
    """Color (or un-color) the cards of an existing game with the host's current theme. Only how the cards look
    changes; card numbers, squares and check codes stay the same, so cards already printed still work."""
    r = require_host(request)
    if r:
        return r
    g = _owned_game(request, db, code)
    if not g:
        return RedirectResponse(url='/host', status_code=302)
    g.paper_theme = themes.theme_for_user_id(_game_host_uid(db, g)) if mode == 'theme' else ''
    db.commit()
    return RedirectResponse(url=f'/host/game/{g.code}/paper', status_code=302)


@router.post('/host/game/{code}/paper/regenerate')
def host_paper_regenerate(request: Request, code: str, db: Session = Depends(get_db)):
    """Rebuild every paper card's squares from the playlist as it is now. Card numbers and check codes stay the
    same, so the old printed cards stop matching: reprint them all. Not while a game is being played."""
    r = require_host(request)
    if r:
        return r
    g = _owned_game(request, db, code)
    if not g:
        return RedirectResponse(url='/host', status_code=302)
    if (g.status or '').lower() == 'started':
        return __host_err_redirect("A game is being played with these cards. Finish it (or use Play again) before regenerating them.")
    cards = _paper_cards(db, g)
    if not cards:
        return RedirectResponse(url=f'/host/game/{g.code}/paper', status_code=302)
    host_uid = _game_host_uid(db, g)
    try:
        _current_card_titles(db, g, fresh=True)   # makes sure Spotify can be read before anything is changed
        for k in [k for k in _PLAYLIST_TRACKS_CACHE if k[0] == g.spotify_playlist_id and k[1] == host_uid]:
            _PLAYLIST_TRACKS_CACHE.pop(k, None)
        for p in cards:
            db.query(models.CardSquare).filter(models.CardSquare.player_id == p.id).delete(synchronize_session=False)
            p.token = uuid.uuid4().hex   # card picks are seeded from game code + token: a new token gives a new card
        db.flush()
        for p in cards:
            _ensure_card_squares(db, g, p, host_user_id=host_uid)
            db.flush()   # the next card is checked against this one
        db.commit()
    except Exception as e:
        db.rollback()
        print(f'PAPER_REGEN_FAILED game={g.code}: {e!r}')
        return __host_err_redirect("Couldn't regenerate the paper cards: the playlist couldn't be loaded from Spotify. Your cards are unchanged. Check Spotify is connected, then try again.")
    return RedirectResponse(url=f'/host/game/{g.code}/paper', status_code=302)


@router.get('/host/game/{code}/paper/check')
def host_paper_check(request: Request, code: str, db: Session = Depends(get_db)):
    r = require_host(request)
    if r:
        return JSONResponse({'error': 'login required'}, status_code=401)
    g = _owned_game(request, db, code)
    if not g:
        return JSONResponse({'error': 'Game not found'}, status_code=404)
    raw = request.query_params.get('card') or ''
    n = _parse_paper_code(g.code, raw)
    p = _paper_card(db, g, n) if n else None
    if not p:
        return JSONResponse({'ok': False, 'error': "That card isn't from this game. Check the code on the card, e.g. 12-KXR."}, status_code=404)
    squares = _card_squares(db, p)
    played, valid, closest = _card_verdict(squares, _played_keys(db, g), g.win_pattern)
    won = (db.query(models.BingoClaim).filter(models.BingoClaim.player_id == p.id, models.BingoClaim.status == 'accepted',
                                              models.BingoClaim.claim_round == _current_round(g)).first())
    return JSONResponse({
        'ok': True,
        'card_number': p.card_number,
        'code': paper_card_code(g.code, p.card_number),
        'squares': [{'pos': int(sq.pos), 'title': sq.title, 'free': bool(sq.is_free), 'played': int(sq.pos) in played} for sq in squares],
        'valid_lines': [{'name': l['name'], 'positions': l['positions']} for l in valid],
        'closest': ({'name': closest['name'], 'missing': closest['missing'], 'positions': closest['positions']} if closest else None),
        'already_won': bool(won),
    })


@router.post('/host/game/{code}/paper/claim')
async def host_paper_claim(request: Request, code: str, db: Session = Depends(get_db)):
    """Record the host's decision on a paper card's call as a claim (Accept/Reject), like a phone claim."""
    r = require_host(request)
    if r:
        return JSONResponse({'error': 'login required'}, status_code=401)
    g = _owned_game(request, db, code)
    if not g:
        return JSONResponse({'error': 'Game not found'}, status_code=404)
    try:
        body = await request.json()
    except Exception:
        body = {}
    n = _parse_paper_code(g.code, str(body.get('card') or ''))
    p = _paper_card(db, g, n) if n else None
    if not p:
        return JSONResponse({'error': "That card isn't from this game."}, status_code=404)
    status = 'accepted' if str(body.get('status') or '').lower().startswith('accept') else 'rejected'
    rnd = _current_round(g)

    squares = _card_squares(db, p)
    played, valid, closest = _card_verdict(squares, _played_keys(db, g), g.win_pattern)
    if valid:
        line = valid[0]['positions']
        detail = f"Auto-valid bingo line: {line} mk={','.join(str(x) for x in sorted(line))}"
    else:
        miss = closest['missing'] if closest else []
        sig = ','.join(str(x) for x in sorted(closest['positions'])) if closest else ''
        detail = f"Bingo line not yet played: missing={miss!r} mk={sig}"

    if status == 'accepted':
        # No repeat wins: once per round, and never again with the same line in a later round
        prev = (db.query(models.BingoClaim)
                  .filter(models.BingoClaim.player_id == p.id, models.BingoClaim.status == 'accepted').all())
        if any(int(getattr(c, 'claim_round', 0) or 0) == rnd for c in prev):
            return JSONResponse({'error': f'Card {p.card_number} has already won this round.'}, status_code=409)
        sig_now = detail.split(' mk=')[-1]
        if any((c.detail or '').split(' mk=')[-1] == sig_now for c in prev):
            return JSONResponse({'error': f'Card {p.card_number} already won with that. A new bingo needs a different set of squares.'}, status_code=409)

    claim = models.BingoClaim(game_id=g.id, player_id=p.id, auto_valid=bool(valid), status=status,
                              detail=detail, claim_round=rnd, pattern=pattern_key(g.win_pattern))
    db.add(claim)
    db.commit()
    await _announce_claim_decision(db, g.code, claim)
    return JSONResponse({'ok': True, 'status': status, 'claim_id': claim.id})


@router.get('/host/game/{code}/paper/missing')
def host_paper_missing(request: Request, code: str, db: Session = Depends(get_db)):
    """Out-of-date report for the notices on the game, saved-games and print pages, and the Start Game check.
    ?fresh=1 reads the playlist from Spotify now instead of the 5-minute cache."""
    r = require_host(request)
    if r:
        return JSONResponse({'error': 'login required'}, status_code=401)
    g = _owned_game(request, db, code)
    if not g:
        return JSONResponse({'error': 'Game not found'}, status_code=404)
    rep = _paper_stale_report(db, g, fresh=(request.query_params.get('fresh') == '1'))
    rep['status'] = g.status
    return JSONResponse(rep)


@router.post('/host/game/{code}/paper/update')
def host_paper_update(request: Request, code: str, db: Session = Depends(get_db)):
    """Swap the songs that are no longer in the playlist for other songs from it, on only the cards that have
    them. Card numbers and check codes stay the same; every other card is untouched. Prefers replacements that
    don't give the card a winning line another card already has. Not while a game is being played."""
    r = require_host(request)
    if r:
        return JSONResponse({'error': 'login required'}, status_code=401)
    g = _owned_game(request, db, code)
    if not g:
        return JSONResponse({'error': 'Game not found'}, status_code=404)
    if (g.status or '').lower() == 'started':
        return JSONResponse({'error': "A game is being played with these cards. Finish it (or use Play again) before updating them."}, status_code=409)
    try:
        pool = _current_card_titles(db, g, fresh=True)
    except Exception:
        return JSONResponse({'error': "Couldn't read the playlist from Spotify. Check Spotify is connected and try again."}, status_code=502)
    cur = {t.lower() for t in pool}
    rng = random.SystemRandom()

    players = {p.id: p for p in db.query(models.Player).filter(models.Player.game_id == g.id).all()}
    squares = {}
    for sq in db.query(models.CardSquare).filter(models.CardSquare.player_id.in_(list(players))).all():
        squares.setdefault(sq.player_id, {})[int(sq.pos)] = sq

    def layout(pid):
        return [None if squares[pid][i].is_free else (squares[pid][i].title or '').lower() for i in range(25)]

    line_sets = {pid: _card_line_sets(layout(pid)) for pid in squares}
    updated, failed, replaced = [], [], 0
    for pid, p in sorted(players.items(), key=lambda kv: (kv[1].card_number or 0)):
        if not p.is_paper or pid not in squares:
            continue
        bad = [pos for pos, sq in squares[pid].items() if not sq.is_free and (sq.title or '').lower() not in cur]
        if not bad:
            continue
        present = {(sq.title or '').lower() for sq in squares[pid].values() if not sq.is_free}
        others = set().union(*[ls for q, ls in line_sets.items() if q != pid]) if len(line_sets) > 1 else set()
        ok = True
        for pos in bad:
            cands = [t for t in pool if t.lower() not in present]
            if not cands:
                ok = False
                break
            rng.shuffle(cands)
            best, best_shared = None, None
            for t in cands[:80]:
                lay = layout(pid); lay[pos] = t.lower()
                shared = len(_card_line_sets(lay) & others)
                if best is None or shared < best_shared:
                    best, best_shared = t, shared
                    if shared == 0:
                        break
            squares[pid][pos].title = best
            present.add(best.lower())
            replaced += 1
        line_sets[pid] = _card_line_sets(layout(pid))
        (updated if ok else failed).append(int(p.card_number))
    db.commit()
    return JSONResponse({'ok': True, 'updated': sorted(updated), 'failed': sorted(failed), 'replaced': replaced})
