"""Who won what in a game: the winner of each round and how many wins each player has, from the accepted bingo claims."""
from . import models
from .avatars import avatar_info
from .cards import pattern_label
from .common import _current_round


def scoreboard(db, g) -> dict:
    rows = (db.query(models.BingoClaim, models.Player)
              .join(models.Player, models.Player.id == models.BingoClaim.player_id)
              .filter(models.BingoClaim.game_id == g.id, models.BingoClaim.status == 'accepted')
              .order_by(models.BingoClaim.created_at.asc(), models.BingoClaim.id.asc()).all())
    wins = [{'round': int(c.claim_round or 0) + 1, 'pattern': pattern_label(c.pattern), 'name': p.name, 'pic': avatar_info(p.avatar, p.avatar_color)} for c, p in rows]
    count, first_win = {}, {}
    for i, (c, p) in enumerate(rows):
        count[p.id] = count.get(p.id, 0) + 1
        first_win.setdefault(p.id, i)
    standings = [{'name': p.name, 'wins': count[p.id], 'pic': avatar_info(p.avatar, p.avatar_color)}
                 for p in sorted({p.id: p for _, p in rows}.values(), key=lambda p: (-count[p.id], first_win[p.id]))]
    return {'round': _current_round(g) + 1, 'wins': wins, 'standings': standings}
