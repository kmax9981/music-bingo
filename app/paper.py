"""Printed paper cards: card codes, check/claim verdicts, stale-card reports."""
import hmac
import time
import sqlalchemy as sa
import uuid
import hashlib
import re
from . import models
from .cards import WIN_PATTERNS, pattern_key, _clean_card_title, _ensure_card_squares, _fetch_playlist_tracks_uncached
from .security import COOKIE_SECRET
from .common import _game_host_uid, _upper_code


# Printed paper bingo cards. A paper card is a Player with is_paper=True and a card_number (1, 2, 3...
# per game), so card squares, claims and the no-repeat-win rule work exactly as for phone players.
# The printed check code ("12-KXR") is derived from the game code + card number with the app secret, so
# a made-up number on a scrap of paper doesn't check out, and nothing extra is stored.
PAPER_MAX_CARDS = 100


PAPER_DEFAULT_CARDS = 30


_CHECK_LETTERS = 'ABCDEFGHJKLMNPQRSTUVWXYZ'  # no I or O (look like 1 and 0)


_LOGO_MAX_BYTES = 2 * 1024 * 1024  # after the browser has shrunk it (see the event picker)



def _paper_check_letters(game_code: str, card_number: int) -> str:
    key = COOKIE_SECRET.encode()
    d = hmac.new(key, f'{_upper_code(game_code)}:{int(card_number)}'.encode(), hashlib.sha256).digest()
    return ''.join(_CHECK_LETTERS[b % len(_CHECK_LETTERS)] for b in d[:3])


def paper_card_code(game_code: str, card_number: int) -> str:
    return f'{int(card_number)}-{_paper_check_letters(game_code, card_number)}'


def _parse_paper_code(game_code: str, raw: str):
    """Card number for a typed code ("12-KXR", "12 kxr", "12KXR"), or None if it isn't a card of this game."""
    v = re.sub(r'[^A-Za-z0-9]', '', raw or '').upper()
    m = re.fullmatch(r'(\d{1,3})([A-Z]{3})', v)
    if not m:
        return None
    n = int(m.group(1))
    return n if hmac.compare_digest(_paper_check_letters(game_code, n), m.group(2)) else None


def _norm_cmp(x: str) -> str:
    # Same matching as the claim check (): letters, digits, spaces
    x = ''.join(ch for ch in (x or '').strip().lower() if ch.isalnum() or ch.isspace())
    return ' '.join(x.split())


def _played_keys(db, g):
    keys = []
    for (t,) in db.query(models.PlayedTrack.title).filter(models.PlayedTrack.game_id == g.id).all():
        n = _norm_cmp(t)
        if n:
            keys.append(n)
    return keys


def _title_played(title: str, played_keys) -> bool:
    nt = _norm_cmp(title)
    # either contains the other: card titles keep subtitles ("My Own Summer (Shove It)"), played ones don't
    return bool(nt) and any(p and (nt in p or p in nt) for p in played_keys)


def _paper_cards(db, g):
    return (db.query(models.Player)
              .filter(models.Player.game_id == g.id, models.Player.is_paper == sa.true())
              .order_by(models.Player.card_number.asc()).all())


def _paper_card(db, g, card_number):
    return (db.query(models.Player)
              .filter(models.Player.game_id == g.id, models.Player.is_paper == sa.true(),
                      models.Player.card_number == int(card_number)).first())


def _card_squares(db, p):
    return (db.query(models.CardSquare).filter(models.CardSquare.player_id == p.id)
              .order_by(models.CardSquare.pos.asc()).all())


def _host_event(db, uid, event_id):
    """A saved event, only if it belongs to this host."""
    try:
        vid = int(event_id)
    except Exception:
        return None
    return db.query(models.Event).filter(models.Event.id == vid, models.Event.host_user_id == uid).first()


def _create_paper_cards(db, g, count: int):
    """Add up to `count` paper cards (100 per game in all). Returns the new cards, numbered on from the last."""
    have = db.query(sa.func.count(models.Player.id)).filter(models.Player.game_id == g.id, models.Player.is_paper == sa.true()).scalar() or 0
    n = max(0, min(int(count), PAPER_MAX_CARDS - int(have)))
    if n == 0:
        return []
    host_uid = _game_host_uid(db, g)
    max_no = db.query(sa.func.max(models.Player.number)).filter(models.Player.game_id == g.id).scalar() or 0
    max_card = db.query(sa.func.max(models.Player.card_number)).filter(models.Player.game_id == g.id).scalar() or 0
    made = []
    for i in range(n):
        cn = int(max_card) + 1 + i
        p = models.Player(game_id=g.id, number=int(max_no) + 1 + i, name=f'Card {cn}', admitted=True,
                          token=uuid.uuid4().hex, is_paper=True, card_number=cn)
        db.add(p)
        db.flush()
        _ensure_card_squares(db, g, p, host_user_id=host_uid)
        db.flush()  # the next card is checked against this one
        made.append(p)
    db.commit()
    return made


def _card_verdict(squares, played_keys, pattern='line'):
    """Which squares have played, and the winning shapes of this pattern that are complete or closest."""
    by_pos = {int(sq.pos): sq for sq in squares}
    played = {pos for pos, sq in by_pos.items() if sq.is_free or _title_played(sq.title, played_keys)}
    lines = []
    for name, line in WIN_PATTERNS[pattern_key(pattern)][1]:
        missing = [by_pos[pos].title for pos in line if pos not in played and pos in by_pos]
        lines.append({'name': name, 'positions': line, 'missing': missing})
    valid = [l for l in lines if not l['missing']]
    closest = min(lines, key=lambda l: len(l['missing'])) if lines else None
    return played, valid, closest


def _event_json(v):
    return {'id': v.id, 'name': v.name or '', 'has_logo': bool(v.logo),
            'logo_url': f'/host/events/{v.id}/logo' if v.logo else None}


_STALE_TITLES_CACHE = {}
_STALE_TITLES_TTL_S = 20   # short, so a playlist you just changed shows up quickly (the tests shorten it)


def _current_card_titles(db, g, fresh: bool = False):
    """The game's songs as they'd appear on a card now (version tags cleaned), unique, in playlist order.
    Raises if Spotify can't be read. fresh=True skips the 5-minute cache (used when starting or updating)."""
    host_uid = _game_host_uid(db, g)
    key = (g.spotify_playlist_id, host_uid)
    hit = _STALE_TITLES_CACHE.get(key)
    if not fresh and hit and (time.monotonic() - hit[0]) < _STALE_TITLES_TTL_S:
        return list(hit[1])
    tracks = _fetch_playlist_tracks_uncached(db, g.spotify_playlist_id, 'US', 100, 0, host_uid)
    out, seen = [], set()
    for row in (tracks or []):
        tr = (row.get('track') or row) if isinstance(row, dict) else {}   # Spotify playlist items: {track: {name}}
        name = (tr.get('name') or '') if isinstance(tr, dict) else ''
        if not name or (isinstance(tr, dict) and tr.get('is_local')):
            continue
        t = _clean_card_title(name)
        if t and t.lower() not in seen:
            seen.add(t.lower()); out.append(t)
    _STALE_TITLES_CACHE[key] = (time.monotonic(), list(out))
    return out


def _paper_card_titles(db, g):
    """{card_number: [song titles]} for this game's paper cards (FREE squares left out)."""
    rows = (db.query(models.Player.card_number, models.CardSquare.title)
              .join(models.CardSquare, models.CardSquare.player_id == models.Player.id)
              .filter(models.Player.game_id == g.id, models.Player.is_paper == sa.true(), models.CardSquare.is_free == sa.false()).all())
    out = {}
    for n, t in rows:
        out.setdefault(int(n), []).append(t)
    return out


def _paper_stale_report(db, g, fresh: bool = False):
    """Are the printed cards out of date against the playlist? Songs REMOVED since printing can't be won (the
    cards that have them need updating); songs ADDED are fine, they just aren't on any card."""
    by_card = _paper_card_titles(db, g)
    if not by_card:
        return {'paper_cards': False, 'missing': [], 'affected_cards': [], 'total_cards': 0, 'new_songs': 0, 'unchecked': False}
    try:
        current = _current_card_titles(db, g, fresh=fresh)
    except Exception:
        return {'paper_cards': True, 'missing': [], 'affected_cards': [], 'total_cards': len(by_card), 'new_songs': 0, 'unchecked': True}
    cur = {t.lower() for t in current}
    missing = sorted({t for ts in by_card.values() for t in ts if t.lower() not in cur})
    affected = sorted(n for n, ts in by_card.items() if any(t.lower() not in cur for t in ts))
    on_cards = {t.lower() for ts in by_card.values() for t in ts}
    return {'paper_cards': True, 'missing': missing, 'affected_cards': affected, 'total_cards': len(by_card),
            'new_songs': len([t for t in current if t.lower() not in on_cards]), 'unchecked': False}


# Scripts the printed cards can't spare room for: a title keeps its Latin-letter name and drops a translation or a
# transliteration in these (Gangnam Style (강남스타일) prints as "Gangnam Style")
_ASIAN_SCRIPTS = re.compile(r'[\u0E00-\u0E7F\u1100-\u11FF\u2E80-\u303F\u3040-\u30FF\u3100-\u312F\u3130-\u318F\u31A0-\u31FF\u3400-\u4DBF'
                            r'\u4E00-\u9FFF\uA960-\uA97F\uAC00-\uD7FF\uF900-\uFAFF\uFF00-\uFFEF]')
_BRACKETED = re.compile(r'\s*[\(\[（【][^\)\]）】]*[\)\]）】]')


def paper_display_title(title: str) -> str:
    """The title as printed on a paper card: bracketed text written in an Asian script is left out, and so is any
    remaining Asian-script text, as long as the title still has Latin letters. A title that is entirely in such a
    script is printed as it is."""
    t = title or ''
    out = _BRACKETED.sub(lambda m: '' if _ASIAN_SCRIPTS.search(m.group(0)) else m.group(0), t)
    if re.search(r'[A-Za-z\u00C0-\u024F]', out):
        out = _ASIAN_SCRIPTS.sub('', out)
    out = re.sub(r'\s+', ' ', out).strip()
    inner = re.fullmatch(r'[\(\[（【]([^\)\]）】]*)[\)\]）】]', out)   # "東京 (Tokyo)" leaves "(Tokyo)": print "Tokyo"
    if inner and inner.group(1).strip():
        out = inner.group(1).strip()
    return out or t
