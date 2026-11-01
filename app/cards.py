"""Bingo cards: reading a game's playlist, building 5x5 cards, checking lines."""
import threading
import time
import random
import hashlib
from fastapi.responses import JSONResponse
from . import models, spotify
from .util import clean_song_title, clean_title_for_card, normalize_key
from typing import List, Optional, Set
from .common import _upper_code
from .errors import best_effort, log_swallowed


def _clean_card_title(title: str) -> str:
    # Bingo squares: version tags off ("- Original 1983 Mix", "(UK 12" Remix)", "- Re-Recorded"),
    # meaningful brackets kept ("My Own Summer (Shove It)"). Same rules as every other title display.
    return clean_song_title(title)


# Playlist tracks cache: every player joining a game needs the same track list, so fetch it from
# Spotify once and reuse it instead of re-paging the whole playlist per join.
# Key: (playlist_id, host_user_id, market, offset, limit). Value: (fetched_at, items).
_PLAYLIST_TRACKS_CACHE = {}


_PLAYLIST_TRACKS_CACHE_TTL_S = 300


_PLAYLIST_TRACKS_LOCKS = {}


_PLAYLIST_TRACKS_LOCKS_GUARD = threading.Lock()


def _fetch_playlist_tracks(db, playlist_id: str, market: str = "US", limit: int = 100, offset: int = 0, host_user_id=None, **kwargs):
    """Fetch ALL playlist tracks (paged) via Spotify Web API, cached for a few minutes.

    Accepts host_user_id for token lookup; also tolerates legacy kwargs like uid/host_user_id.
    """
    # tolerate older callsites that pass uid/host_user_id via kwargs
    if host_user_id is None:
        if "host_user_id" in kwargs and kwargs.get("host_user_id") is not None:
            host_user_id = kwargs.get("host_user_id")
        elif "uid" in kwargs and kwargs.get("uid") is not None:
            host_user_id = kwargs.get("uid")
    key = (playlist_id, host_user_id, market, int(offset or 0), int(limit or 100))
    with _PLAYLIST_TRACKS_LOCKS_GUARD:
        lock = _PLAYLIST_TRACKS_LOCKS.setdefault(key, threading.Lock())
    # Per-key lock: when many players join at once, only the first one hits Spotify.
    with lock:
        hit = _PLAYLIST_TRACKS_CACHE.get(key)
        if hit and (time.monotonic() - hit[0]) < _PLAYLIST_TRACKS_CACHE_TTL_S:
            return hit[1]
        items = _fetch_playlist_tracks_uncached(db, playlist_id, market, limit, offset, host_user_id)
        if items:
            _PLAYLIST_TRACKS_CACHE[key] = (time.monotonic(), items)
        return items


def _fetch_playlist_tracks_uncached(db, playlist_id, market, limit, offset, host_user_id):
    items = []
    off = int(offset or 0)
    lim = int(limit or 100)
    # Spotify allows up to 100 per page for playlist tracks
    if lim <= 0 or lim > 100:
        lim = 100
    while True:
        j = spotify.api_get(
            db,
            f"/playlists/{playlist_id}/tracks",
            params={"market": market, "limit": lim, "offset": off},
            host_user_id=host_user_id,
        )
        if not j or not isinstance(j, dict):
            break
        batch = j.get("items") or []
        if not isinstance(batch, list) or not batch:
            break
        items.extend(batch)
        # stop when we've reached the end
        if j.get("next") is None:
            break
        off += lim
    return items


def _rng_for_player(game_code: str, player_token: str) -> random.Random:
    seed_src = f"{_upper_code(game_code)}|{player_token}".encode("utf-8", "ignore")
    seed = int(hashlib.sha256(seed_src).hexdigest()[:16], 16)
    return random.Random(seed)


def _card_layout(picked):
    """25 lowercased titles in square order for 24 picked songs (None in the FREE center)."""
    it = iter([t[1].lower() for t in picked])
    return [None if pos == 12 else next(it, '') for pos in range(25)]


def _card_line_sets(layout):
    """Each of the 12 bingo lines as the set of its song titles (the FREE square isn't a song)."""
    return {frozenset(layout[i] for i in line if layout[i]) for line in _bingo_lines()}


def _pick_unique_card(db, g, p, cleaned, rng, tries=200):
    """Pick 24 songs for player/card p, unlike every other card in the game (paper and phone): never an
    identical card, and where the playlist allows it, no winning line another card already has (two
    cards would then win on the same song with the same five squares). Falls back to the card sharing
    the fewest lines when no card avoids them all (small playlists)."""
    others = {}
    rows = (db.query(models.CardSquare.player_id, models.CardSquare.pos, models.CardSquare.title, models.CardSquare.is_free)
              .join(models.Player, models.Player.id == models.CardSquare.player_id)
              .filter(models.Player.game_id == g.id, models.Player.id != p.id).all())
    for pid, pos, title, is_free in rows:
        others.setdefault(pid, [''] * 25)[int(pos)] = None if is_free else (title or '').lower()
    taken_cards = {tuple(v) for v in others.values()}
    taken_lines = set()
    for v in others.values():
        taken_lines |= _card_line_sets(v)

    best, best_shared = None, None
    for _ in range(tries):
        rng.shuffle(cleaned)
        picked = cleaned[:24]
        layout = _card_layout(picked)
        if tuple(layout) in taken_cards:
            continue
        shared = len(_card_line_sets(layout) & taken_lines)
        if shared == 0:
            return list(picked)
        if best is None or shared < best_shared:
            best, best_shared = list(picked), shared
    return best if best is not None else list(cleaned[:24])


def _ensure_card_squares(db, g, p, host_user_id=None):
    existing = db.query(models.CardSquare).filter(models.CardSquare.player_id == p.id).count()
    if existing and existing >= 25:
        return
    db.query(models.CardSquare).filter(models.CardSquare.player_id == p.id).delete(synchronize_session=False)

    tracks = _fetch_playlist_tracks(db, g.spotify_playlist_id, market="US", limit=100, host_user_id=host_user_id)


    def _track_row_to_tuple(row):

        """Return (track_id, title, artist) from tuple/list OR dict OR nested Spotify structures."""

        try:

            if row is None:

                return (None, None, "")

            if isinstance(row, (list, tuple)):

                tid = row[0] if len(row) > 0 else None

                title = row[1] if len(row) > 1 else None

                artist = row[2] if len(row) > 2 else ""

                return (tid, title, artist or "")

            if not isinstance(row, dict):

                return (None, None, "")

    

            base = row.get("track")

            if base is None and isinstance(row.get("item"), dict):

                base = row["item"].get("track")

            if base is None:

                base = row

    

            tid = (base.get("id") or base.get("track_id") or base.get("uri") or base.get(0))

            title = (base.get("name") or base.get("title") or base.get(1))

    

            artist_val = (base.get("artist") or base.get("artists") or row.get("artist") or row.get("artists") or base.get(2) or "")

            artist = ""

            if isinstance(artist_val, str):

                artist = artist_val

            elif isinstance(artist_val, list):

                parts = []

                for a in artist_val:

                    if not a:

                        continue

                    if isinstance(a, dict):

                        nm = a.get("name")

                        if nm:

                            parts.append(str(nm))

                    else:

                        parts.append(str(a))

                artist = ", ".join(parts)

            elif isinstance(artist_val, dict):

                nm = artist_val.get("name")

                artist = str(nm) if nm else ""

            else:

                try:

                    artist = str(artist_val)

                except Exception:
                    pass

                    artist = ""

    

            return (tid, title, artist or "")

        except Exception:

            return (None, None, "")

    

    seen = set()

    cleaned = []

    for row in (tracks or []):

        tid, title, artist = _track_row_to_tuple(row)

        if not title:

            continue

        try:

            ct = _clean_card_title(title)

            if not ct:

                ct = title

        except Exception:

            ct = title

        k = str(ct).lower()

        if not k or k in seen:

            continue

        seen.add(k)

        cleaned.append((tid, ct, artist or ""))

    rng=_rng_for_player(g.code, p.token)
    if len(cleaned) < 24:
        # (auto-fix) Normalize track rows (tuple/list OR dict) safely
        def _track_row_to_tuple(row):
            try:
                if row is None:
                    return (None, None, "")
                # dict-like rows (common when using JSON-ish structures)
                if isinstance(row, dict):
                    tid = row.get(0) or row.get('id') or row.get('track_id') or row.get('uri')
                    title = row.get(1) or row.get('name') or row.get('title')
                    artist = row.get(2) or row.get('artist') or row.get('artists') or ""
                    # artists may be list of dicts
                    if isinstance(artist, list):
                        try:
                            artist = ', '.join([(a.get('name') if isinstance(a, dict) else str(a)) for a in artist if a])
                        except Exception:
                            artist = ', '.join([str(a) for a in artist if a])
                    return (tid, title, artist or "")
                # tuple/list rows
                if isinstance(row, (list, tuple)):
                    tid = row[0] if len(row) > 0 else None
                    title = row[1] if len(row) > 1 else None
                    artist = row[2] if len(row) > 2 else ""
                    return (tid, title, artist or "")
                return (None, None, "")
            except Exception:
                return (None, None, "")
        
        cleaned = []
        for row in (tracks or []):
            tid, title, artist = _track_row_to_tuple(row)
            if not title:
                continue
            try:
                ct = _clean_card_title(title) or title
            except Exception:
                ct = title
            cleaned.append((tid, ct, artist or ""))

    tmp=[]
    used=set()
    for tid, title, artist in cleaned:
        k=(title or "").lower()
        if not k or k in used:
            continue
        used.add(k)
        tmp.append((tid, title, artist))
    cleaned=tmp

    picked = _pick_unique_card(db, g, p, cleaned, rng)

    pos_to_title={}
    i=0
    for pos in range(25):
        if pos == 12:
            continue
        pos_to_title[pos] = picked[i][1] if i < len(picked) else "—"
        i += 1

    for pos in range(25):
        if pos == 12:
            sq=models.CardSquare(player_id=p.id, pos=pos, title="FREE", is_free=True)
        else:
            sq=models.CardSquare(player_id=p.id, pos=pos, title=pos_to_title.get(pos,"—"), is_free=False)
        db.add(sq)


def _bingo_lines() -> List[List[int]]:
    lines=[]
    for r in range(5):
        lines.append([r*5 + c for c in range(5)])
    for c in range(5):
        lines.append([r*5 + c for r in range(5)])
    lines.append([0,6,12,18,24])
    lines.append([4,8,12,16,20])
    return lines


# What counts as bingo. Each pattern is a list of (name, squares): a card wins when it has every square of ANY entry
# (the FREE centre is always marked). "line" is the classic: any row, column or diagonal.
_LINE_NAMES = ['row 1', 'row 2', 'row 3', 'row 4', 'row 5',
               'column 1', 'column 2', 'column 3', 'column 4', 'column 5',
               'the diagonal from top left', 'the diagonal from top right']
WIN_PATTERNS = {
    'line': ('Any line', list(zip(_LINE_NAMES, _bingo_lines()))),
    'corners': ('Four corners', [('the four corners', [0, 4, 20, 24])]),
    'x': ('Letter X', [('the X', [0, 4, 6, 8, 12, 16, 18, 20, 24])]),
    'plus': ('Plus sign', [('the plus sign', [2, 7, 10, 11, 12, 13, 14, 17, 22])]),
    'frame': ('Picture frame', [('the picture frame', [p for p in range(25) if p % 5 in (0, 4) or p // 5 in (0, 4)])]),
    'full': ('Full card', [('the full card', list(range(25)))]),
}
DEFAULT_PATTERN = 'line'


def pattern_key(value) -> str:
    """A known pattern key, or the classic one for anything else (old games, a bad value)."""
    v = str(value or '').strip().lower()
    return v if v in WIN_PATTERNS else DEFAULT_PATTERN


def pattern_label(value) -> str:
    return WIN_PATTERNS[pattern_key(value)][0]


def pattern_squares(value) -> List[int]:
    """Every square any win of this pattern uses (for the little picture of it): all 25 would be the full card."""
    return sorted({p for _, sq in WIN_PATTERNS[pattern_key(value)][1] for p in sq}) if pattern_key(value) != 'line' else []


def pattern_info(value) -> dict:
    """What the pages and sockets need to show a pattern: its key, its name and which squares it uses (empty for any line)."""
    k = pattern_key(value)
    return {'key': k, 'label': pattern_label(k), 'squares': pattern_squares(k)}


def _is_bingo(marked: Set[int], pattern: str = DEFAULT_PATTERN) -> Optional[List[int]]:
    marked=set(marked or set())
    marked.add(12)  # FREE
    for _, squares in WIN_PATTERNS[pattern_key(pattern)][1]:
        if all((p in marked) for p in squares):
            return squares
    return None


def _card_title_pool(db, g, uid):
    """The different song titles a game's cards can use, from its playlist. Returns (titles, error_response); the
    response is set (and titles empty) when Spotify isn't connected or the playlist is too short for a card."""
    if not (uid and spotify.get_valid_access_token(db, host_user_id=uid)):
        return [], JSONResponse({'error': 'Spotify not connected'}, status_code=400)
    items = []
    offset = 0
    while True:
        data = spotify.api_get(db, f'/playlists/{g.spotify_playlist_id}/tracks', params={'limit': 100, 'offset': offset}, host_user_id=uid)
        batch = data.get('items', [])
        items.extend(batch)
        if len(batch) < 100:
            break
        offset += 100

    seen = set()
    uniq = []
    for it in items:
        tr = (it or {}).get('track') or {}
        if not tr or tr.get('is_local') or tr.get('type') != 'track':
            continue
        name = clean_title_for_card(tr.get('name') or '')
        if not name:
            continue
        k = normalize_key(name)
        if k in seen:
            continue
        seen.add(k)
        uniq.append(name)
    if len(uniq) < 24:
        return [], JSONResponse({'error': f'That playlist has only {len(uniq)} different songs. A game needs at least 24.'}, status_code=400)
    return uniq, None


def _admit_with_card(db, p, uniq):
    """Mark a phone player admitted and give them a card (24 random different songs and the FREE square) if they have none yet.
    Returns False when a card couldn't be made."""
    import secrets as _secrets
    p.admitted = True
    if db.query(models.CardSquare).filter(models.CardSquare.player_id == p.id).first():
        return True
    pool = uniq[:]
    chosen = []
    usedk = set()
    while len(chosen) < 24 and pool:
        pick = pool[_secrets.randbelow(len(pool))]
        pool.remove(pick)
        k = normalize_key(pick)
        if k in usedk:
            continue
        usedk.add(k)
        chosen.append(pick)
    if len(chosen) < 24:
        return False
    idx = 0
    for pos in range(25):
        if pos == 12:
            db.add(models.CardSquare(player_id=p.id, pos=pos, title='FREE', is_free=True))
            continue
        db.add(models.CardSquare(player_id=p.id, pos=pos, title=chosen[idx], is_free=False))
        idx += 1
    return True


# Cache playlist track ids + total for a short time per game code (best-effort).
PLAYLIST_TRACK_CACHE = {}


def _bingo_get_playlist_track_ids(db, host_user_id: int, playlist_uri_or_id: str, code_u: str = "", cache_ttl_s: int = 60):
    # Return (set_of_track_ids, total). Best-effort; cached by code_u for cache_ttl_s seconds.
    try:
        import time as _time
        now = int(_time.time())
    except Exception:
        now = 0

    code_key = (code_u or "").strip().upper()
    if code_key:
        with best_effort():
            c = PLAYLIST_TRACK_CACHE.get(code_key) or {}
            ts = int(c.get('ts') or 0)
            if ts and now and (now - ts) <= int(cache_ttl_s):
                ids = c.get('ids') or set()
                total = int(c.get('total') or 0)
                return (set(ids), total)

    pid = (playlist_uri_or_id or "").strip()
    if pid.startswith('spotify:playlist:'):
        pid = pid.split(':')[-1].strip()
    if not pid:
        return (set(), 0)

    ids = set()
    total = 0
    try:
        meta = spotify.api_get(db, f"/playlists/{pid}", host_user_id=host_user_id) or {}
        total = int((((meta or {}).get('tracks') or {}).get('total') or 0))
    except Exception as e:
        log_swallowed(e)
        total = 0

    with best_effort():
        limit = 100
        offset = 0
        while True:
            # market=from_token returns the IDs Spotify actually plays for this account; for "relinked"
            # songs that differs from the playlist's own ID, which comes back as linked_from.id. Keep both.
            j = spotify.api_get(db, f"/playlists/{pid}/tracks?fields=items(track(id,linked_from(id))),total&limit={limit}&offset={offset}&market=from_token", host_user_id=host_user_id) or {}
            items = (j.get('items') or []) if isinstance(j, dict) else []
            for it in items:
                with best_effort():
                    tr = (it or {}).get('track') or {}
                    for tid in (tr.get('id'), (tr.get('linked_from') or {}).get('id')):
                        tid = (tid or '').strip()
                        if tid:
                            ids.add(tid)
            if not items:
                break
            offset += limit
            if total and offset >= total:
                break
            if offset >= 2000:
                break

    if code_key:
        with best_effort():
            PLAYLIST_TRACK_CACHE[code_key] = {'ts': now, 'ids': set(ids), 'total': int(total or 0)}
    return (set(ids), int(total or 0))


def _bingo_clean_title_display(s: str) -> str:
    # Now-playing title for hosts/players: same version-tag rules as the bingo squares
    try:
        return clean_song_title(s or "")
    except Exception:
        return (s or "").strip()


from .common import templates  # noqa: E402
templates.env.globals['win_pattern_options'] = [(k, v[0]) for k, v in WIN_PATTERNS.items()]
templates.env.globals['pattern_info'] = pattern_info
from .avatars import AVATARS, COLORS, avatar_info  # noqa: E402
templates.env.globals['avatar_options'] = AVATARS
templates.env.globals['avatar_colors'] = COLORS
templates.env.globals['avatar_info'] = avatar_info
