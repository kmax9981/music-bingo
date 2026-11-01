"""Host: deciding and removing bingo claims."""
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from ..db import get_db
from .. import models
from ..ws import hub
from ..claims import _announce_claim_decision
from ..common import _current_round, _host_user_from_session, _norm_code, _owned_game, _owner_key_for_user, _upper_code, require_host
from ..errors import best_effort

router = APIRouter()


@router.post('/host/game/{code}/claim/{claim_id}/delete')
async def host_claim_delete(request: Request, code: str, claim_id: int, db: Session = Depends(get_db)):
    # Clear a rejected claim off the host's list (only rejected ones; pending and accepted claims stay)
    r = require_host(request)
    if r:
        return r
    g = _owned_game(request, db, _upper_code(_norm_code(code)))
    if not g:
        return JSONResponse({'ok': False, 'error': 'Game not found'}, status_code=404)
    claim = (db.query(models.BingoClaim)
               .filter(models.BingoClaim.id == claim_id, models.BingoClaim.game_id == g.id).first())
    if not claim:
        return JSONResponse({'ok': False, 'error': 'Claim not found'}, status_code=404)
    if (claim.status or '') != 'rejected':
        return JSONResponse({'ok': False, 'error': 'Only rejected claims can be removed from the list'}, status_code=409)
    db.delete(claim)
    db.commit()
    with best_effort():
        await hub.broadcast_host(g.code, {'type': 'claims'})
    return JSONResponse({'ok': True})


@router.post('/host/game/{code}/claim/{claim_id}/set')
async def host_claim_set(request: Request, code: str, claim_id: int, db: Session = Depends(get_db)):
    r = require_host(request)
    if r:
        return r

    # Resolve host user + owner_key to ensure host can only modify their own game's claims
    u = None
    try:
        u = _host_user_from_session(request, db)
    except Exception:
        u = None
    if not u:
        return JSONResponse({'error': 'not authed'}, status_code=401)

    owner_key = _owner_key_for_user(u)
    code_u = (code or '').strip().upper()

    g = (db.query(models.Game)
        .filter(models.Game.code == code_u, models.Game.owner_key == owner_key)
        .first())
    if not g:
        return JSONResponse({'error': 'Game not found'}, status_code=404)

    # Parse payload (support JSON or query/form). Front-end may send ?action=accept or JSON {action: "..."}.
    payload = {}
    try:
        payload = await request.json()
        if not isinstance(payload, dict):
            payload = {}
    except Exception:
        payload = {}

    # Query params fallback
    try:
        qp = dict(request.query_params)
    except Exception:
        qp = {}

    # Form fallback
    try:
        form = await request.form()
        fp = dict(form)
    except Exception:
        fp = {}

    action = (payload.get('action') or payload.get('status') or qp.get('action') or qp.get('status') or fp.get('action') or fp.get('status') or '').strip().lower()

    return await decide_claim(db, g, claim_id, action)


async def decide_claim(db, g, claim_id: int, action: str):
    """Accept or reject one of this game's claims in the current round, then tell the players and the host.
    Used by the host and by a co-host (who gets the same decision, nothing else)."""
    code_u = g.code
    claim = (db.query(models.BingoClaim)
        .filter(models.BingoClaim.id == claim_id, models.BingoClaim.game_id == g.id, models.BingoClaim.claim_round == _current_round(g), )
        .first())
    if not claim:
        return JSONResponse({'error': 'Claim not found'}, status_code=404)

    # Normalize action/status values
    if action in ('accept', 'accepted', 'approve', 'approved', 'valid', 'ok', 'true', 'yes'):
        new_status = 'accepted'
    elif action in ('reject', 'rejected', 'deny', 'denied', 'invalid', 'bad', 'false', 'no'):
        new_status = 'rejected'
    else:
        return JSONResponse({'error': 'missing action/status', 'hint': 'Use action=accept|reject (or status=accepted|rejected).'}, status_code=400)

    # Apply updates (defensive about column names)
    with best_effort():
        if hasattr(claim, 'status'):
            claim.status = new_status
        if hasattr(claim, 'action'):
            claim.action = new_status
        if hasattr(claim, 'decision'):
            claim.decision = new_status
        if hasattr(claim, 'reviewed'):
            claim.reviewed = True
        if hasattr(claim, 'reviewed_at'):
            import datetime as _dt
            claim.reviewed_at = _dt.datetime.utcnow()
        if hasattr(claim, 'decided_at'):
            import datetime as _dt
            claim.decided_at = _dt.datetime.utcnow()

    try:
        db.commit()  # notify players for overlay + refresh claims
    except Exception as e:
        db.rollback()
        return JSONResponse({'error': f'db commit failed: {e}'}, status_code=400)

    await _announce_claim_decision(db, code_u, claim)

    return JSONResponse({'ok': True, 'claim_id': int(claim_id), 'status': new_status})
