"""Deleting data for good: a game with everything that hangs off it, and a host account with everything it owns.
(Nothing here commits: the caller does.)"""
from . import models
from .common import _owner_key_for_user


def delete_game(db, g) -> None:
    """The game, its players and their cards, every bingo claim and the played-track list."""
    pids = [pid for (pid,) in db.query(models.Player.id).filter(models.Player.game_id == g.id).all()]
    db.query(models.BingoClaim).filter(models.BingoClaim.game_id == g.id).delete(synchronize_session=False)
    db.query(models.PlayedTrack).filter(models.PlayedTrack.game_id == g.id).delete(synchronize_session=False)
    if pids:
        db.query(models.CardSquare).filter(models.CardSquare.player_id.in_(pids)).delete(synchronize_session=False)
    db.query(models.Player).filter(models.Player.game_id == g.id).delete(synchronize_session=False)
    db.query(models.Game).filter(models.Game.id == g.id).delete(synchronize_session=False)


def delete_host(db, u) -> None:
    """A host account and everything it owns: games (phone and paper cards, players, history), Play Alone sessions, events
    with their logos, saved playlists and the saved Spotify login."""
    for g in db.query(models.Game).filter(models.Game.owner_key == _owner_key_for_user(u)).all():
        delete_game(db, g)
    db.query(models.Event).filter(models.Event.host_user_id == u.id).delete(synchronize_session=False)
    db.query(models.SavedPlaylist).filter(models.SavedPlaylist.created_by_user_id == u.id).delete(synchronize_session=False)
    db.query(models.HostSpotifyToken).filter(models.HostSpotifyToken.host_user_id == u.id).delete(synchronize_session=False)
    db.query(models.HostUser).filter(models.HostUser.id == u.id).delete(synchronize_session=False)
