import re
import secrets


def gen_code(n: int = 5) -> str:
    alphabet = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'
    return ''.join(secrets.choice(alphabet) for _ in range(n))

# Words that mark a title part as a version tag rather than the song's name: "Clear - Original 1983 Mix",
# "Pump Up The Volume (UK 12" Remix)", "Smooth Criminal - Re-Recorded", "Alive - 2006 Remaster".
_VERSION_WORDS = (r'(?:remaster(?:ed)?|re-?record(?:ed|ing)?|re-?mix(?:ed)?|mix|edit|version|live|mono|stereo|'
                  r'feat\.?|featuring|from|demo|instrumental|acoustic|bonus\s+track|deluxe|explicit|clean|'
                  r'anniversary|extended|single|radio|12"|7"|12\u201d|7\u201d|12 inch|7 inch)')
# The last " - ..." part (any dash, with spaces around it; "Re-Recorded" has a bare hyphen) when it
# contains a version word
_SPACED_DASH = r'\s[-\u2013\u2014]\s'
_VERSION_DASH_RE = re.compile(r'\s+[-\u2013\u2014]\s+(?=(?:(?!' + _SPACED_DASH + r').)*?(?<![A-Za-z])' + _VERSION_WORDS
                              + r'(?![A-Za-z]))(?:(?!' + _SPACED_DASH + r').)*$', re.I)
# A trailing (...) or [...] part that contains a version word
_VERSION_BRACKET_RE = re.compile(r'\s*(?:\((?=[^)]*(?<![A-Za-z])' + _VERSION_WORDS + r'(?![A-Za-z]))[^)]*\)|\[(?=[^\]]*(?<![A-Za-z])' + _VERSION_WORDS + r'(?![A-Za-z]))[^\]]*\])\s*$', re.I)


def clean_song_title(title: str) -> str:
    """Song title without version tags, keeping parts that belong to the name ("My Own Summer (Shove It)").
    Shared by bingo squares, played tracks and the now-playing displays, so they all agree."""
    t = re.sub(r'\s+', ' ', (title or '').strip())
    while True:  # tags can stack: "Song (Remix) - 2011 Remaster"
        t2 = _VERSION_BRACKET_RE.sub('', _VERSION_DASH_RE.sub('', t)).strip()
        if t2 == t or not t2:
            break
        t = t2
    return t or (title or '').strip()


def clean_title_for_card(title: str) -> str:
    # Played-track records and playlist counting: version tags off, and any other bracketed part too
    t = clean_song_title(title)
    t = re.sub(r'\s*\([^\)]*\)\s*', ' ', t)  # (..)
    t = re.sub(r'\s*\[[^\]]*\]\s*', ' ', t)  # [..]
    t = re.sub(r'\s+', ' ', t).strip()
    return t or title.strip()

def normalize_key(s: str) -> str:
    s = s.strip().lower()
    s = re.sub(r'\s+', ' ', s)
    return s
