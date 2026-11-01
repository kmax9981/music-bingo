"""Co-host: a second person, on their own phone, decides bingo claims for one game through a secret link the host makes.
They can accept or reject claims and see the round, the pattern and the songs played; starting, pausing, continuing or ending
the game, and everything else, stays with the host. The link only works for that game, and the host can turn it off."""
import hmac
import secrets

from fastapi import APIRouter, Depends, Request, WebSocket
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.websockets import WebSocketDisconnect
from sqlalchemy.orm import Session

from .. import models, settings
from ..avatars import avatar_info
from ..cards import pattern_info
from ..common import _claim_reason, _current_round, _norm_code, _owned_game, _upper_code, require_host, templates
from ..db import SessionLocal, get_db
from ..errors import best_effort
from ..ws import hub
from .game_claims import decide_claim

router = APIRouter()
_NO_STORE = {'Cache-Control': 'no-store', 'Referrer-Policy': 'no-referrer', 'X-Robots-Tag': 'noindex, nofollow'}


def _game_for_link(db, code, token):
    """The game this link belongs to while the link is on and the game has not ended, else None."""
    g = db.query(models.Game).filter(models.Game.code == _upper_code(_norm_code(code)), models.Game.game_type == 'hosted').first()
    want = (g.cohost_token or '') if g else ''
    if not g or not want or not hmac.compare_digest(want.encode(), (token or '').encode()):
        return None
    return g


def _link_for(g) -> str:
    return f'{settings.public_base()}/cohost/{g.code}/{g.cohost_token}'


@router.post('/host/game/{code}/cohost')
async def host_cohost_link(request: Request, code: str, db: Session = Depends(get_db)):
    """Make (or replace) the co-host link, or turn it off: {"action": "on" | "off"}."""
    r = require_host(request)
    if r:
        return r
    g = _owned_game(request, db, code)
    if not g:
        return JSONResponse({'ok': False, 'error': 'Game not found'}, status_code=404)
    try:
        body = await request.json()
    except Exception:
        body = {}
    action = str((body or {}).get('action') or '').strip().lower() if isinstance(body, dict) else ''
    if action == 'off':
        g.cohost_token = None
    elif action == 'on':
        g.cohost_token = secrets.token_urlsafe(16)   # a new link every time, so an old one stops working
    else:
        return JSONResponse({'ok': False, 'error': 'action must be on or off'}, status_code=400)
    db.add(g)
    db.commit()
    return JSONResponse({'ok': True, 'url': _link_for(g) if g.cohost_token else ''})


@router.get('/host/game/{code}/cohost')
def host_cohost_current(request: Request, code: str, db: Session = Depends(get_db)):
    r = require_host(request)
    if r:
        return r
    g = _owned_game(request, db, code)
    if not g:
        return JSONResponse({'ok': False, 'error': 'Game not found'}, status_code=404)
    return JSONResponse({'ok': True, 'url': _link_for(g) if g.cohost_token else ''})


@router.get('/cohost/{code}/{token}', response_class=HTMLResponse)
def cohost_page(request: Request, code: str, token: str, db: Session = Depends(get_db)):
    g = _game_for_link(db, code, token)
    if not g or g.status == 'ended':
        return HTMLResponse('This co-host link is not working. Ask the host for a new one.', status_code=404, headers=_NO_STORE)
    resp = templates.TemplateResponse(request, 'cohost.html', {'request': request, 'game': g, 'token': token})
    resp.headers.update(_NO_STORE)
    return resp


@router.get('/cohost/{code}/{token}/state')
def cohost_state(code: str, token: str, db: Session = Depends(get_db)):
    g = _game_for_link(db, code, token)
    if not g:
        return JSONResponse({'ok': False, 'error': 'link_off'}, status_code=404, headers=_NO_STORE)
    cur = _current_round(g)
    claims = (db.query(models.BingoClaim, models.Player)
                .join(models.Player, models.Player.id == models.BingoClaim.player_id)
                .filter(models.BingoClaim.game_id == g.id, models.BingoClaim.claim_round == cur)
                .order_by(models.BingoClaim.created_at.asc(), models.BingoClaim.id.asc()).all())
    played = (db.query(models.PlayedTrack).filter(models.PlayedTrack.game_id == g.id)
                .order_by(models.PlayedTrack.seq.desc()).limit(8).all())
    return JSONResponse({
        'ok': True, 'name': g.name, 'status': g.status, 'round': cur + 1, 'pattern': pattern_info(g.win_pattern),
        'claims': [{'id': c.id, 'name': pl.name, 'pic': avatar_info(pl.avatar, pl.avatar_color), 'status': c.status, 'auto_valid': bool(c.auto_valid), 'why': _claim_reason(c.detail or '') if not c.auto_valid else '',
                    'pattern': pattern_info(c.pattern)['label']} for c, pl in claims],
        'played': [{'title': t.title, 'artist': t.artist} for t in played],
    }, headers=_NO_STORE)


@router.post('/cohost/{code}/{token}/claim/{claim_id}')
async def cohost_decide(request: Request, code: str, token: str, claim_id: int, db: Session = Depends(get_db)):
    g = _game_for_link(db, code, token)
    if not g or g.status == 'ended':
        return JSONResponse({'ok': False, 'error': 'link_off'}, status_code=404, headers=_NO_STORE)
    try:
        body = await request.json()
    except Exception:
        body = {}
    action = str((body or {}).get('action') or '').strip().lower() if isinstance(body, dict) else ''
    if action not in ('accept', 'reject'):
        return JSONResponse({'ok': False, 'error': 'action must be accept or reject'}, status_code=400)
    return await decide_claim(db, g, claim_id, action)


@router.websocket('/ws/cohost/{code}/{token}')
async def ws_cohost(websocket: WebSocket, code: str, token: str):
    code_u = _upper_code(code)
    db = SessionLocal()
    try:
        ok = _game_for_link(db, code_u, token) is not None
    finally:
        db.close()
    if not ok:
        await websocket.close(code=1008)
        return
    await hub.connect_host(code_u, websocket)   # hears what the host's page hears
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        await hub.disconnect_host(code_u, websocket)
