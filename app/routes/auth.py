"""Host login/logout, account page and admin user management."""
from urllib.parse import quote
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from sqlalchemy.orm import Session
from ..db import get_db
from .. import models
from ..login_guard import LOGIN_BLOCKED_MSG as _LOGIN_BLOCKED_MSG, login_blocked as _login_blocked, login_failed as _login_failed, login_keys as _login_keys, login_succeeded as _login_succeeded
from ..passwords import pw_hash as _pw_hash, pw_verify as _pw_verify
from ..http_headers import safe_next_path as _safe_next_path
from .. import themes, settings
from urllib.parse import urlparse
from ..cleanup import delete_host
from ..common import _bootstrap_admin_user, _host_user_from_session, host_session_value, _require_admin, clear_cookie, host_authed, require_host, set_cookie, templates
from ..errors import best_effort, log_swallowed, rollback_quietly

router = APIRouter()


@router.get('/host/login', response_class=HTMLResponse)
def host_login_page(request: Request, db: Session = Depends(get_db)):
    # Legacy path: keep working but use unified login page
    return RedirectResponse(url='/login?next=/host', status_code=302)


@router.post('/host/login')
def host_login(request: Request):
    # Legacy path: the one login handler is POST /login (307 keeps the posted form)
    return RedirectResponse(url='/login', status_code=307)


@router.get('/host/logout')
def host_logout_get(request: Request):
    resp = RedirectResponse(url='/', status_code=302)
    clear_cookie(resp, 'host_session')
    clear_cookie(resp, 'host_state')
    return resp


@router.post('/host/logout')
def host_logout(request: Request):
    resp = RedirectResponse(url='/', status_code=302)
    clear_cookie(resp, 'host_session')
    clear_cookie(resp, 'host_state')
    return resp


@router.get('/host/whoami')
def host_whoami(request: Request, db: Session = Depends(get_db)):
    # Lightweight endpoint for UI menus
    if not host_authed(request):
        return JSONResponse({'authed': False}, status_code=200)
    u = _host_user_from_session(request, db)
    if not u:
        return JSONResponse({'authed': False}, status_code=200)
    return JSONResponse({
        'authed': True,
        'username': getattr(u, 'username', '') or '',
        'is_admin': bool(getattr(u, 'is_admin', False)),
        'uid': int(getattr(u, 'id', 0) or 0),
    }, status_code=200)


@router.get('/host/account', response_class=HTMLResponse)
def host_account_page(
    request: Request,
    db: Session = Depends(get_db),
    ok: str = None,
    error: str = None,
):
    r = require_host(request)
    if r:
        return r
    u = _host_user_from_session(request, db)
    return templates.TemplateResponse(request, 'host_account.html', {
        'request': request,
        'user': u,
        'ok': ok,
        'error': error,
        'must_change': bool(getattr(u, 'must_change_password', False)),
    })


@router.get('/host/options')
def host_options():
    """The Options entry in the user menu: its pages are listed on the left of each one; Account comes first."""
    return RedirectResponse(url='/host/account', status_code=302)


@router.get('/host/themes', response_class=HTMLResponse)
def host_themes_page(request: Request, db: Session = Depends(get_db), ok: str = None, error: str = None):
    r = require_host(request)
    if r:
        return r
    u = _host_user_from_session(request, db)
    return templates.TemplateResponse(request, 'host_themes.html', {
        'request': request,
        'user': u,
        'ok': ok,
        'error': error,
        'current_theme': themes.theme_id(themes.user_spec(u)),
        'custom_colors': themes.parse_custom(getattr(u, 'custom_colors', '')) or themes.DEFAULT_CUSTOM,
    })


@router.post('/host/account/theme')
def host_account_set_theme(request: Request, db: Session = Depends(get_db), theme: str = Form(''),
                           custom_bg: str = Form(''), custom_accent: str = Form(''), custom_highlight: str = Form('')):
    """Pick the color theme for your pages and for the games you host (players see it too). 'custom' also takes
    the host's three colors (page background, buttons, highlight)."""
    r = require_host(request)
    if r:
        return r
    u = _host_user_from_session(request, db)
    if theme.strip().lower() not in {t for t, _ in themes.THEMES}:
        return RedirectResponse(url='/host/themes?error=' + quote('Pick one of the themes shown.'), status_code=302)
    if theme.strip().lower() == 'custom':
        spec = themes.custom_spec(custom_bg, custom_accent, custom_highlight)
        if not spec:
            return RedirectResponse(url='/host/themes?error=' + quote('Pick the three colors for your custom theme.'), status_code=302)
        u.theme = 'custom'
        u.custom_colors = spec[len('custom:'):]
    else:
        u.theme = themes.valid_theme(theme)
    db.commit()
    themes.forget(int(u.id))
    return RedirectResponse(url='/host/themes?ok=' + quote('Theme saved.'), status_code=302)


# The colors are in the URL, so a given color set never changes: browsers can keep it for good. Nothing secret here.
_THEME_CACHE_HEADERS = {'Cache-Control': 'public, max-age=31536000, immutable'}


@router.get('/theme/custom.css')
def custom_theme_css(c: str = ''):
    css = themes.custom_css(c)
    if not css:
        return Response('/* not a color set */', status_code=400, media_type='text/css')
    return Response(css, media_type='text/css', headers=_THEME_CACHE_HEADERS)


@router.get('/theme/custom.json')
def custom_theme_json(c: str = ''):
    """The variables for a color set, for the live preview on the Account page (the page applies them itself)."""
    data = themes.custom_json(c)
    if not data:
        return JSONResponse({'error': 'not a color set'}, status_code=400)
    return JSONResponse(data, headers=_THEME_CACHE_HEADERS)


@router.post('/host/account/password')
def host_account_change_password(
    request: Request,
    db: Session = Depends(get_db),
    current_password: str = Form(...),
    new_password: str = Form(...),
    new_password2: str = Form(...),
):
    r = require_host(request)
    if r:
        return r
    u = _host_user_from_session(request, db)
    if not u:
        return RedirectResponse(url='/login?next=/play', status_code=302)

    cur = (current_password or '')
    npw = (new_password or '')
    npw2 = (new_password2 or '')

    if not _pw_verify(cur, u.password_hash):
        return RedirectResponse(url='/host/account?error=Current%20password%20is%20incorrect', status_code=302)

    if len(npw) < 8:
        return RedirectResponse(url='/host/account?error=New%20password%20must%20be%20at%20least%208%20characters', status_code=302)

    if npw != npw2:
        return RedirectResponse(url='/host/account?error=New%20passwords%20do%20not%20match', status_code=302)

    if getattr(u, 'must_change_password', False) and npw == cur:
        return RedirectResponse(url='/host/account?error=' + quote('Choose a different password from the temporary one.'), status_code=302)

    try:
        u.password_hash = _pw_hash(npw)
        u.must_change_password = False
        db.add(u)
        db.commit()
    except Exception:
        rollback_quietly(db)
        return RedirectResponse(url='/host/account?error=Failed%20to%20update%20password', status_code=302)

    resp = RedirectResponse(url='/host/account?ok=Password%20updated', status_code=302)
    set_cookie(request, resp, 'host_session', host_session_value(u))   # this browser stays logged in; every other session is now invalid
    return resp


@router.get('/host/admin/users', response_class=HTMLResponse)
def host_admin_users(request: Request, db: Session = Depends(get_db)):
    r = require_host(request)
    if r:
        return r
    ar = _require_admin(request, db)
    if ar:
        return ar
    users = db.query(models.HostUser).order_by(models.HostUser.created_at.desc()).all()
    return templates.TemplateResponse(request, 'host_admin_users.html', {
        'request': request, 'users': users,
        'ok': request.query_params.get('ok'), 'error': request.query_params.get('error'),
        'cfg': {'public_url': settings.public_base(), 'public_src': settings.source('PUBLIC_BASE_URL'),
                'spotify_id': settings.spotify_client_id(), 'spotify_id_src': settings.source('SPOTIFY_CLIENT_ID'),
                'spotify_secret_src': settings.source('SPOTIFY_CLIENT_SECRET'), 'redirect_uri': settings.spotify_redirect_uri(),
                'redirect_src': settings.source('SPOTIFY_REDIRECT_URI'), 'redirect_saved': settings.get('SPOTIFY_REDIRECT_URI')},
    })


@router.post('/host/admin/settings')
def host_admin_settings(request: Request, db: Session = Depends(get_db), public_url: str = Form(''), spotify_client_id: str = Form(''),
                        spotify_client_secret: str = Form(''), spotify_redirect_uri: str = Form('')):
    """Admin: the public address and the Spotify developer app. A value set in the server's env file can't be changed here.
    An empty secret box keeps the saved secret."""
    r = require_host(request)
    if r:
        return r
    ar = _require_admin(request, db)
    if ar:
        return ar
    url = (public_url or '').strip().rstrip('/')
    parsed = urlparse(url)
    if url and not (parsed.scheme in ('http', 'https') and parsed.netloc and not parsed.path.strip('/')):
        return RedirectResponse(url='/host/admin/users?error=' + quote('The public address should look like https://bingo.example.com (no path after it).'), status_code=302)
    values = {}
    if not settings.from_env('PUBLIC_BASE_URL'):
        values['PUBLIC_BASE_URL'] = url
    if not settings.from_env('SPOTIFY_CLIENT_ID'):
        values['SPOTIFY_CLIENT_ID'] = spotify_client_id
    if not settings.from_env('SPOTIFY_REDIRECT_URI'):
        values['SPOTIFY_REDIRECT_URI'] = (spotify_redirect_uri or '').strip()
    if not settings.from_env('SPOTIFY_CLIENT_SECRET') and (spotify_client_secret or '').strip():
        values['SPOTIFY_CLIENT_SECRET'] = spotify_client_secret
    settings.save(db, values)
    return RedirectResponse(url='/host/admin/users?ok=' + quote('Settings saved.'), status_code=302)


@router.post('/host/admin/users/create')
def host_admin_users_create(request: Request, db: Session = Depends(get_db), username: str = Form(...), password: str = Form(...), is_admin: str = Form('')):
    r = require_host(request)
    if r:
        return r
    ar = _require_admin(request, db)
    if ar:
        return ar
    uname = (username or '').strip()
    pw = (password or '')
    if not uname or not pw:
        return RedirectResponse(url='/host/admin/users', status_code=302)
    if len(pw) < 8:
        return RedirectResponse(url='/host/admin/users?error=' + quote('The temporary password must be at least 8 characters.'), status_code=302)
    exists = db.query(models.HostUser).filter(models.HostUser.username == uname).first()
    if exists:
        return RedirectResponse(url='/host/admin/users', status_code=302)
    u = models.HostUser(username=uname, password_hash=_pw_hash(pw), is_admin=bool(is_admin), must_change_password=True)   # the host picks their own at first login
    db.add(u)
    db.commit()
    return RedirectResponse(url='/host/admin/users', status_code=302)


@router.post('/host/admin/users/toggle_admin')
def host_admin_users_toggle_admin(request: Request, db: Session = Depends(get_db), user_id: int = Form(...)):
    r = require_host(request)
    if r:
        return r
    ar = _require_admin(request, db)
    if ar:
        return ar
    u = db.query(models.HostUser).filter(models.HostUser.id == user_id).first()
    if u:
        u.is_admin = not bool(u.is_admin)
        db.commit()
    return RedirectResponse(url='/host/admin/users', status_code=302)


# --- Admin user helpers: add missing routes for UI compatibility ---
@router.post('/host/admin/users/set_password')
def host_admin_users_set_password(request: Request, db: Session = Depends(get_db), user_id: int = Form(...), password: str = Form(...)):
    r = require_host(request)
    if r:
        return r
    ar = _require_admin(request, db)
    if ar:
        return ar
    u = db.query(models.HostUser).filter(models.HostUser.id == user_id).first()
    if u and (password or '').strip():
        me = _host_user_from_session(request, db)   # who is asking: ask before the password (and so the session stamp) changes
        own = bool(me and int(me.id) == int(u.id))
        u.password_hash = _pw_hash(password)
        if not own:   # a password an admin sets for someone else is temporary; their own is their choice
            u.must_change_password = True
        db.commit()
        resp = RedirectResponse(url='/host/admin/users', status_code=302)
        if own:
            set_cookie(request, resp, 'host_session', host_session_value(u))   # keep this browser logged in
        return resp
    return RedirectResponse(url='/host/admin/users', status_code=302)


@router.post('/host/admin/users/delete')
def host_admin_users_delete(request: Request, db: Session = Depends(get_db), user_id: int = Form(...)):
    r = require_host(request)
    if r:
        return r
    ar = _require_admin(request, db)
    if ar:
        return ar
    # Safety: don't allow deleting yourself or deleting the last admin
    me = _host_user_from_session(request, db)
    if me and int(getattr(me, 'id', -1)) == int(user_id):
        return RedirectResponse(url='/host/admin/users', status_code=302)
    target = db.query(models.HostUser).filter(models.HostUser.id == user_id).first()
    if not target:
        return RedirectResponse(url='/host/admin/users', status_code=302)
    with best_effort():
        if bool(getattr(target, 'is_admin', False)):
            admin_count = db.query(models.HostUser).filter(models.HostUser.is_admin.is_(True)).count()
            if admin_count <= 1:
                return RedirectResponse(url='/host/admin/users', status_code=302)
    try:
        delete_host(db, target)   # the account and everything it owns
        db.commit()
    except Exception as e:
        rollback_quietly(db)
        log_swallowed(e)
    return RedirectResponse(url='/host/admin/users', status_code=302)


@router.get('/login', response_class=HTMLResponse)
def login_page(request: Request, db: Session = Depends(get_db)):
    _bootstrap_admin_user(db)
    nxt = (request.query_params.get('next') or '').strip()
    return templates.TemplateResponse(request, 'host_login.html', {'request': request, 'next': nxt})


_DUMMY_HASH = []


def _dummy_hash() -> str:
    if not _DUMMY_HASH:
        _DUMMY_HASH.append(_pw_hash('not-a-real-password'))
    return _DUMMY_HASH[0]


@router.post('/login')
def login_post(
    request: Request,
    db: Session = Depends(get_db),
    username: str = Form(...),
    password: str = Form(...),
    next: str = Form(''),
):
    uname = (username or '').strip()
    pw = (password or '')
    if not uname or not pw:
        return templates.TemplateResponse(request, 'host_login.html', {'request': request, 'error': 'Username and password required', 'next': next}, status_code=401)

    keys = _login_keys(request, uname)
    if _login_blocked(keys):
        return templates.TemplateResponse(request, 'host_login.html', {'request': request, 'error': _LOGIN_BLOCKED_MSG, 'next': next}, status_code=429)
    u = db.query(models.HostUser).filter(models.HostUser.username == uname).first()
    if u is None:
        _pw_verify(pw, _dummy_hash())   # an unknown username costs the same time as a wrong password: no probing for real usernames
    if not u or not _pw_verify(pw, u.password_hash):
        _login_failed(keys)
        return templates.TemplateResponse(request, 'host_login.html', {'request': request, 'error': 'Invalid credentials', 'next': next}, status_code=401)
    _login_succeeded(keys)

    dest = _safe_next_path(next)
    resp = RedirectResponse(url=dest, status_code=302)
    set_cookie(request, resp, 'host_session', host_session_value(u))
    return resp
