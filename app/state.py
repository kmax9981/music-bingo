"""Per-game live state shared between the host, player and solo routes (never re-bound, only mutated)."""
import threading


# Cache last known track WS payload per game code for fast player bootstrap after refresh.
# Key: game code (uppercase). Value: dict matching WS 'track' message fields.
LAST_TRACK_STATE = {}


# Per-game timestamp of the last random-restart Play, guarded so concurrent Play requests can't both restart.
_PLAY_RESTART_LOCK = threading.Lock()


_PLAY_RESTARTED_AT = {}
