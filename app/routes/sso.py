"""Optional single sign-in for hosts (see app/oidc.py). The routes answer 404 while it is switched off."""
import hmac
import secrets
from urllib.parse import quote
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session
from ..db import get_db
from .. import models, oidc, settings, usernames
from ..security import sign, unsign
from ..http_headers import safe_next_path as _safe_next_path
from ..common import _require_admin, clear_cookie, host_session_value, require_host, set_cookie, templates

router = APIRouter()
oidc.use_settings(settings.get)   # the Admin page can save these settings; a value in the environment still wins

# The login page asks this for the button and for whether to hide the password form
templates.env.globals['sso_login'] = lambda request: {
    'enabled': oidc.enabled(),
    'name': oidc.provider_name(),
    'hide_local': oidc.hide_local() and (request.query_params.get('local') or '') != '1',
}


def redirect_uri() -> str:
    return settings.public_base() + '/auth/oidc/callback'


def _login_error(request: Request, msg: str, status: int = 400):
    resp = templates.TemplateResponse(request, 'host_login.html', {'request': request, 'error': msg, 'next': ''}, status_code=status)
    clear_cookie(resp, 'oidc_state')
    return resp


@router.get('/auth/oidc/login')
def oidc_login(request: Request, next: str = ''):
    if not oidc.enabled():
        return HTMLResponse('Not found', status_code=404)
    try:
        verifier, challenge = oidc.pkce_pair()
        state = secrets.token_urlsafe(24)
        url = oidc.authorize_url(redirect_uri(), state, challenge)
    except Exception as e:
        print(f'OIDC_LOGIN_FAILED {e!r}')
        return _login_error(request, 'The single sign-in could not be reached just now. Try again in a minute.', 502)
    resp = RedirectResponse(url=url, status_code=302)
    set_cookie(request, resp, 'oidc_state', sign({'state': state, 'verifier': verifier, 'next': _safe_next_path(next)}))
    return resp


@router.get('/auth/oidc/callback')
def oidc_callback(request: Request, db: Session = Depends(get_db), code: str = '', state: str = '', error: str = ''):
    if not oidc.enabled():
        return HTMLResponse('Not found', status_code=404)
    cookie = request.cookies.get('oidc_state', '')
    data = unsign(cookie, max_age=600) if cookie else None
    expected = (data or {}).get('state') or ''
    if not expected or not state or not hmac.compare_digest(state, expected):
        return _login_error(request, 'The sign-in expired or came from another tab. Press the sign-in button again.')
    if error or not code:
        return _login_error(request, 'The sign-in was cancelled or refused.', 403)
    try:
        claims = oidc.claims_for_code(code, redirect_uri(), data.get('verifier') or '')
    except Exception as e:
        print(f'OIDC_CALLBACK_FAILED {e!r}')
        return _login_error(request, 'The sign-in could not be completed. Try again.', 502)
    uname = oidc.local_username(claims)
    u = None
    if uname:
        u = db.query(models.HostUser).filter(models.HostUser.username == uname).first()
        if u is None:   # same name in another letter case
            for cand in db.query(models.HostUser).all():
                if (cand.username or '').lower() == uname.lower():
                    u = cand
                    break
    if u is None:
        print(f'OIDC_NO_ACCOUNT name={uname!r}')
        return _login_error(request, 'You signed in, but there is no Bingo host account for you. Ask the person who runs Bingo.', 403)
    if usernames.is_reserved(u.username):   # the local emergency admin is only ever reached with its own password
        print(f'OIDC_LOCAL_ADMIN_REFUSED name={uname!r}')
        return _login_error(request, 'That account can only sign in with its own password at /login?local=1.', 403)
    resp = RedirectResponse(url=_safe_next_path(data.get('next') or ''), status_code=302)
    set_cookie(request, resp, 'host_session', host_session_value(u, sso=True))
    set_cookie(request, resp, 'host_sso', '1')
    clear_cookie(resp, 'oidc_state')
    return resp


_FIELDS = (('OIDC_ISSUER', 'issuer'), ('OIDC_CLIENT_ID', 'client_id'), ('OIDC_PROVIDER_NAME', 'provider_name'),
           ('OIDC_USERNAME_CLAIM', 'username_claim'))


def admin_cfg() -> dict:
    """What the Admin page shows for the single sign-in: each value and where it comes from ('env', 'saved' or '')."""
    c = {k: {'value': settings.get(k), 'src': settings.source(k)} for k, _ in _FIELDS}
    c['secret_src'] = settings.source('OIDC_CLIENT_SECRET')
    c['hide'] = {'value': oidc.hide_local(), 'src': settings.source('OIDC_HIDE_LOCAL_LOGIN')}
    c['enabled'] = oidc.enabled()
    c['configured'] = oidc.configured()
    c['switch'] = {'on': not oidc.switched_off(), 'src': settings.source('OIDC_ENABLED')}
    c['redirect_uri'] = redirect_uri()
    return c


@router.post('/host/admin/sso')
def admin_sso_save(request: Request, db: Session = Depends(get_db), issuer: str = Form(''), client_id: str = Form(''), client_secret: str = Form(''),
                   provider_name: str = Form(''), username_claim: str = Form(''), hide_local: str = Form(''), enabled: str = Form('')):
    """Admin: the single sign-in settings. A value set in the server's settings file cannot be changed here; an empty secret box keeps the saved secret."""
    r = require_host(request)
    if r:
        return r
    ar = _require_admin(request, db)
    if ar:
        return ar
    iss = (issuer or '').strip()
    if iss and not (iss.startswith('https://') or iss.startswith('http://localhost') or iss.startswith('http://127.0.0.1')):
        return RedirectResponse(url='/host/admin/users?error=' + quote('The provider address should start with https://'), status_code=302)
    posted = {'OIDC_ENABLED': 'true' if (enabled or '').strip() else 'false', 'OIDC_ISSUER': iss, 'OIDC_CLIENT_ID': client_id, 'OIDC_PROVIDER_NAME': provider_name, 'OIDC_USERNAME_CLAIM': username_claim,
              'OIDC_HIDE_LOCAL_LOGIN': 'true' if (hide_local or '').strip() else ''}
    values = {k: v for k, v in posted.items() if not settings.from_env(k)}
    if not settings.from_env('OIDC_CLIENT_SECRET') and (client_secret or '').strip():
        values['OIDC_CLIENT_SECRET'] = client_secret
    settings.save(db, values)
    oidc.forget_discovery()
    return RedirectResponse(url='/host/admin/users?ok=' + quote('Single sign-in settings saved.'), status_code=302)


@router.post('/host/admin/sso/test')
def admin_sso_test(request: Request, db: Session = Depends(get_db)):
    """Admin: check that the provider's address answers (it reads the provider's configuration document)."""
    r = require_host(request)
    if r:
        return r
    ar = _require_admin(request, db)
    if ar:
        return ar
    if not oidc.enabled():
        return RedirectResponse(url='/host/admin/users?error=' + quote('Fill in the provider address, client ID and client secret first.'), status_code=302)
    oidc.forget_discovery()
    try:
        d = oidc.discovery()
        if not (d.get('authorization_endpoint') and d.get('token_endpoint') and d.get('userinfo_endpoint')):
            raise RuntimeError('the provider did not list the addresses a sign-in needs')
    except Exception as e:
        print(f'OIDC_TEST_FAILED {e!r}')
        return RedirectResponse(url='/host/admin/users?error=' + quote('The provider did not answer as expected. Check the provider address.'), status_code=302)
    return RedirectResponse(url='/host/admin/users?ok=' + quote('The provider answered. Press the sign-in button on the login page to try a real sign-in.'), status_code=302)
