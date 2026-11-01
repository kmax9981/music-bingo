"""Color themes hosts can pick (Account page). The colors themselves live in static/themes.css; this module knows
which theme ids exist and which theme a page should wear: the host's own theme on host pages, and the game owner's
theme on the pages players see, so a game looks the same on every phone.

A theme is written as a "spec": a theme id ('midnight', 'ocean', ...) or, for the host's own colors,
'custom:RRGGBB-RRGGBB-RRGGBB' (page background, button color, highlight color). Everything else the pages need
(panels, text, borders, field colors) is worked out from those three colors in custom_vars()."""
import re
from markupsafe import Markup
from .common import _host_user_id_from_game, templates
from .db import SessionLocal
from .security import unsign
from . import models

DEFAULT_THEME = 'midnight'
THEMES = [
    ('midnight', 'Midnight Purple'),
    ('ocean', 'Ocean Blue'),
    ('emerald', 'Emerald'),
    ('sunset', 'Sunset'),
    ('rose', 'Rose'),
    ('graphite', 'Graphite'),
    ('maize', 'Maize & Blue'),
    ('light', 'Light'),
    ('custom', 'Custom'),
]
_IDS = {t for t, _ in THEMES}
_BUILTIN = _IDS - {'custom'}
_LIGHT_BUILTIN = {'light'}
DEFAULT_CUSTOM = ('0b0b20', '8b5cf6', 'a78bfa')   # where the color pickers start: Midnight Purple's colors
_HEX = re.compile(r'^[0-9a-f]{6}$')
_CACHE = {}     # host user id -> theme id (this app runs one worker; forget() is called whenever a theme changes)


def parse_custom(colors):
    """'rrggbb-rrggbb-rrggbb' (a leading '#' on each part is fine) -> three lowercase hex strings, or None."""
    parts = [p.strip().lstrip('#').lower() for p in str(colors or '').split('-')]
    return tuple(parts) if len(parts) == 3 and all(_HEX.match(p) for p in parts) else None


def custom_spec(bg, accent, highlight):
    c = parse_custom('-'.join(str(x or '') for x in (bg, accent, highlight)))
    return 'custom:' + '-'.join(c) if c else None


def valid_theme(value) -> str:
    """A saved theme value or form input -> a clean spec; anything unknown falls back to the default theme."""
    v = str(value or '').strip().lower()
    if v.startswith('custom:'):
        c = parse_custom(v[7:])
        return 'custom:' + '-'.join(c) if c else DEFAULT_THEME
    return v if v in _BUILTIN else DEFAULT_THEME


def theme_id(spec) -> str:
    return 'custom' if str(spec or '').startswith('custom:') else valid_theme(spec)


def theme_label(spec) -> str:
    return dict(THEMES).get(theme_id(spec), 'Midnight Purple')


# ---- Custom colors -> every variable the stylesheets use ----
def _rgb(h):
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _mix(a, b, t):
    return tuple(round(x + (y - x) * t) for x, y in zip(a, b))


def _lum(c):
    ch = [x / 255 for x in c]
    ch = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in ch]
    return 0.2126 * ch[0] + 0.7152 * ch[1] + 0.0722 * ch[2]


def _contrast(a, b):
    la, lb = sorted((_lum(a), _lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def _hex(c):
    return '#%02x%02x%02x' % tuple(c)


def _sp(c):
    return '%d %d %d' % tuple(c)


def _rgba(c, a):
    return 'rgba(%d, %d, %d, %s)' % (c[0], c[1], c[2], a)


def _readable_on(fg, bg, minimum=4.5, toward=None):
    """Move fg towards white or black until it reads on bg."""
    toward = toward or ((255, 255, 255) if _lum(bg) < 0.4 else (0, 0, 0))
    for _ in range(14):
        if _contrast(fg, bg) >= minimum:
            break
        fg = _mix(fg, toward, 0.12)
    return fg


def _best_text_on(c):
    white, dark = (255, 255, 255), (17, 17, 17)
    return white if _contrast(white, c) >= 3.2 else dark


def custom_vars(bg_hex, accent_hex, highlight_hex):
    """(tone, {css variable: value}) for a host's own three colors. tone is 'dark' or 'light' (from the background)."""
    bg, acc, hi = _rgb(bg_hex), _rgb(accent_hex), _rgb(highlight_hex)
    white, black = (255, 255, 255), (0, 0, 0)
    dark = _lum(bg) < 0.35
    v = {}
    if dark:
        panel = _mix(bg, white, 0.07)
        text = _mix(bg, white, 0.93)
        v.update({'--bgTop': _hex(_mix(bg, white, 0.04)), '--bgMid': _hex(bg), '--bgBot': _hex(_mix(bg, black, 0.35)),
                  '--panelTop': _rgba(_mix(bg, white, 0.10), 0.78), '--panelBot': _rgba(_mix(bg, white, 0.05), 0.86),
                  '--panelSolid': 'rgb(%d, %d, %d)' % panel, '--border': _rgba(_mix(bg, white, 0.6), 0.28),
                  '--text': _hex(text), '--muted': _rgba(text, 0.65), '--ink-rgb': _sp(white), '--shade-rgb': _sp(black), '--shade-k': '1',
                  '--field-bg': _rgba(_mix(bg, black, 0.5), 0.55), '--field-border': _rgba(_mix(bg, white, 0.7), 0.22),
                  '--btn-border': _rgba(_mix(bg, white, 0.7), 0.18), '--menu-bg': _rgba(_mix(bg, black, 0.3), 0.97), '--menu-text': _hex(text),
                  '--shadow': '0 28px 70px rgba(0,0,0,0.55)'})
    else:
        panel = white
        text = _mix(bg, black, 0.9)
        v.update({'--bgTop': _hex(_mix(bg, white, 0.45)), '--bgMid': _hex(bg), '--bgBot': _hex(_mix(bg, black, 0.06)),
                  '--panelTop': _rgba(white, 0.96), '--panelBot': _rgba(_mix(white, bg, 0.1), 0.98), '--panelSolid': 'rgb(255, 255, 255)',
                  '--border': _rgba(_mix(bg, black, 0.6), 0.22), '--text': _hex(text), '--muted': _rgba(text, 0.68),
                  '--ink-rgb': _sp(text), '--shade-rgb': _sp(text), '--shade-k': '0.28',
                  '--field-bg': '#ffffff', '--field-border': _rgba(text, 0.32), '--btn-border': _rgba(text, 0.22),
                  '--menu-bg': '#ffffff', '--menu-text': _hex(text), '--shadow': '0 18px 44px %s' % _rgba(_mix(bg, black, 0.6), 0.16)})
    hi = _readable_on(hi, panel)
    on_acc = _best_text_on(acc)
    on_hi = _best_text_on(hi)
    banner = _mix(acc, black, 0.72)
    v.update({'--accent': _hex(acc), '--accent2': _hex(hi), '--accent-rgb': _sp(acc), '--accent2-rgb': _sp(hi),
              '--marked-rgb': _sp(hi if dark else acc), '--btn-text': _hex(on_acc), '--lit-text': _hex(on_hi),
              '--paper-letter-text': _hex(on_hi), '--glow2-rgb': _sp(hi),
              '--banner-bg': _hex(banner), '--banner-big': _hex(_readable_on(hi, banner, 4.5, white)), '--banner-text': '#f5f3ff'})
    return ('dark' if dark else 'light'), v


_PREVIEW_SELECTORS = 'html[data-theme="custom"], .themeCard[data-theme="custom"]'


def custom_css(colors) -> str:
    c = parse_custom(colors)
    if not c:
        return ''
    tone, v = custom_vars(*c)
    body = ''.join(f'  {k}: {val};\n' for k, val in v.items())
    return f'/* custom theme {"-".join(c)} ({tone}) */\n{_PREVIEW_SELECTORS}{{\n{body}}}\n'


def custom_json(colors):
    c = parse_custom(colors)
    if not c:
        return None
    tone, v = custom_vars(*c)
    return {'tone': tone, 'vars': v}


def tone_of_spec(spec) -> str:
    tid = theme_id(spec)
    if tid == 'custom':
        return custom_vars(*parse_custom(str(spec)[7:]))[0]
    return 'light' if tid in _LIGHT_BUILTIN else 'dark'


def user_spec(u) -> str:
    """A host's saved theme as a spec: their own colors when they picked Custom (and have saved some)."""
    if str(getattr(u, 'theme', '') or '') == 'custom':
        c = parse_custom(getattr(u, 'custom_colors', ''))
        if c:
            return 'custom:' + '-'.join(c)
    return valid_theme(getattr(u, 'theme', DEFAULT_THEME))


def theme_for_user_id(uid: int) -> str:
    if uid in _CACHE:
        return _CACHE[uid]
    theme = DEFAULT_THEME
    db = SessionLocal()
    try:
        u = db.query(models.HostUser).filter(models.HostUser.id == uid).first()
        if u is not None:
            theme = user_spec(u)   # a spec: 'ocean' or 'custom:...'
    except Exception:
        theme = DEFAULT_THEME
    finally:
        db.close()
    _CACHE[uid] = theme
    return theme


def forget(uid: int = None) -> None:
    if uid is None:
        _CACHE.clear()
    else:
        _CACHE.pop(uid, None)


def _spec_of(request, game=None) -> str:
    """The theme spec for the page being rendered."""
    uid = _host_user_id_from_game(game) if game is not None else None
    if not uid:
        try:
            data = unsign(request.cookies.get('host_session', '') or '')
            uid = int(data.get('uid')) if isinstance(data, dict) and data.get('uid') else None
        except Exception:
            uid = None
    return theme_for_user_id(uid) if uid else DEFAULT_THEME


def theme_of(request, game=None) -> str:
    """The theme id for the page being rendered ('custom' for a host's own colors)."""
    return theme_id(_spec_of(request, game))


def theme_attrs(request, game=None) -> Markup:
    """The attributes for <html>: data-theme, plus data-tone="light" for themes with dark text on light panels."""
    return theme_attrs_for_spec(_spec_of(request, game))


def theme_attrs_for_spec(spec) -> Markup:
    return Markup('data-theme="%s"%s' % (theme_id(spec), ' data-tone="light"' if tone_of_spec(spec) == 'light' else ''))


def theme_head_for_spec(spec) -> Markup:
    """The stylesheet link a custom theme needs (the colors are in the URL, so each color set caches for good)."""
    c = parse_custom(str(spec)[7:]) if theme_id(spec) == 'custom' else None
    if not c:
        return Markup('')
    return Markup('<link rel="stylesheet" href="/theme/custom.css?c=%s" />' % '-'.join(c))   # only validated hex digits go into the page


def theme_head(request, game=None) -> Markup:
    return theme_head_for_spec(_spec_of(request, game))


from .version import VERSION  # noqa: E402
templates.env.globals['app_version'] = VERSION
templates.env.globals['theme_of'] = theme_of
templates.env.globals['theme_attrs'] = theme_attrs
templates.env.globals['theme_attrs_for_spec'] = theme_attrs_for_spec
templates.env.globals['theme_head'] = theme_head
templates.env.globals['theme_head_for_spec'] = theme_head_for_spec
templates.env.globals['theme_label'] = theme_label
templates.env.globals['THEMES'] = THEMES
templates.env.globals['THEME_NAMES'] = dict(THEMES)
from .static_files import static_url  # noqa: E402
templates.env.globals['static_url'] = static_url
