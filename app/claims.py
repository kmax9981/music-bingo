"""Telling players and the host what happened to a bingo claim."""
from . import models
from .ws import hub
from .errors import best_effort


async def _announce_claim_decision(db, code_u, claim):
    """Tell phone players about an accepted/rejected claim (winner overlay) and refresh claim lists.
    Shared by phone claims and paper cards."""
    with best_effort():
        st = (getattr(claim, "status", "") or "")
        if st == "accepted":
            winner_name = "Player"
            winner_playerno = None

            # Robust: look up player directly via claim.player_id (do not rely on relationship name/loading)
            with best_effort():
                pid = getattr(claim, "player_id", None)
                if pid is not None:
                    pl = (db.query(models.Player)
                          .filter(models.Player.id == pid)
                          .first())
                    if pl is not None:
                        winner_name = getattr(pl, "name", None) or winner_name
                        winner_playerno = getattr(pl, "number", None)

            msg = {
                "type": "overlay",
                "overlay": "bingo_accepted",
                "winner_name": winner_name,
                "winner_playerno": winner_playerno,
                "claim_id": getattr(claim, "id", None),
            }
            with best_effort():
                await hub.broadcast_players(code_u, msg)
            with best_effort():
                await hub.broadcast_host(code_u, {"type": "room", "event": "bingo", "winner_name": winner_name})

        if st == "rejected":
            msg = {"type": "claim_status", "status": "rejected", "claim_id": getattr(claim, "id", None)}
            with best_effort():
                await hub.broadcast_players(code_u, msg)

    # Notify host + players to refresh claims without manual page reload
    with best_effort():
        await hub.broadcast_host(code_u, {'type': 'claims_updated'})
        await hub.broadcast_players(code_u, {'type': 'claims_updated'})
