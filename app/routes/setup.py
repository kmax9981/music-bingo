"""First-run setup screen: create the admin account and (optionally) save the public address and Spotify app details."""
import re
from urllib.parse import urlparse
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session
from ..db import get_db
from .. import models, settings, setup_flow
from ..common import host_session_value, set_cookie, templates
from ..passwords import pw_hash

router = APIRouter()
_USERNAME = re.compile(r'^[A-Za-z0-9._-]{3,40}$')


def _guess_public_url(request: Request) -> str:
    """The address the visitor is using right now (behind a proxy: the forwarded host and scheme)."""
    host = (request.headers.get('x-forwarded-host') or request.headers.get('host') or '').split(',')[0].strip()
    proto = (request.headers.get('x-forwarded-proto') or request.url.scheme or 'http').split(',')[0].strip()
    return f'{proto}://{host}' if host else settings.public_base()


def _page(request, status=200, error='', values=None):
    v = {'username': 'admin', 'public_url': settings.from_env('PUBLIC_BASE_URL') or settings.get('PUBLIC_BASE_URL') or _guess_public_url(request),
         'spotify_client_id': settings.spotify_client_id(), 'spotify_redirect_uri': settings.get('SPOTIFY_REDIRECT_URI')}
    v.update(values or {})
    return templates.TemplateResponse(request, 'setup.html', {
        'request': request, 'error': error, 'v': v,
        'env_public': settings.source('PUBLIC_BASE_URL') == 'env', 'env_spotify': settings.source('SPOTIFY_CLIENT_ID') == 'env',
    }, status_code=status)


@router.get('/setup', response_class=HTMLResponse)
def setup_page(request: Request):
    if not setup_flow.needs_setup():
        return RedirectResponse(url='/login', status_code=302)
    return _page(request)


@router.post('/setup')
def setup_submit(request: Request, db: Session = Depends(get_db),
                 username: str = Form(''), password: str = Form(''), password2: str = Form(''),
                 public_url: str = Form(''), spotify_client_id: str = Form(''), spotify_client_secret: str = Form(''),
                 spotify_redirect_uri: str = Form('')):
    if not setup_flow.needs_setup():
        return RedirectResponse(url='/login', status_code=302)
    keep = {'username': username.strip(), 'public_url': public_url.strip(), 'spotify_client_id': spotify_client_id.strip(),
            'spotify_redirect_uri': spotify_redirect_uri.strip()}
    uname = username.strip()
    if not _USERNAME.match(uname):
        return _page(request, 400, 'The username needs 3 to 40 letters, digits, dots, dashes or underscores.', keep)
    if len(password) < 8:
        return _page(request, 400, 'The password must be at least 8 characters.', keep)
    if password != password2:
        return _page(request, 400, 'The two passwords do not match.', keep)
    url = public_url.strip().rstrip('/')
    parsed = urlparse(url)
    if url and not (parsed.scheme in ('http', 'https') and parsed.netloc and not parsed.path.strip('/')):
        return _page(request, 400, 'The public address should look like https://bingo.example.com (no path after it).', keep)
    redirect = spotify_redirect_uri.strip()
    if redirect and not urlparse(redirect).scheme in ('http', 'https'):
        return _page(request, 400, 'The Spotify redirect address should start with http:// or https://', keep)
    if db.query(models.HostUser).count() > 0:   # somebody finished setup a moment ago
        return RedirectResponse(url='/login', status_code=302)
    u = models.HostUser(username=uname, password_hash=pw_hash(password), is_admin=True)
    db.add(u)
    db.commit()
    values = {}
    if url and not settings.from_env('PUBLIC_BASE_URL'):
        values['PUBLIC_BASE_URL'] = url
    if not settings.from_env('SPOTIFY_CLIENT_ID'):
        values['SPOTIFY_CLIENT_ID'] = spotify_client_id
    if not settings.from_env('SPOTIFY_REDIRECT_URI'):
        values['SPOTIFY_REDIRECT_URI'] = redirect
    if not settings.from_env('SPOTIFY_CLIENT_SECRET') and spotify_client_secret.strip():
        values['SPOTIFY_CLIENT_SECRET'] = spotify_client_secret
    settings.save(db, values)
    setup_flow.finished()
    resp = RedirectResponse(url='/host', status_code=302)
    set_cookie(request, resp, 'host_session', host_session_value(u))
    return resp


async def setup_redirect_middleware(request: Request, call_next):
    """Until the first account exists, send every page visit to the setup screen."""
    path = request.url.path
    if (path.startswith('/static/') or path in ('/setup', '/favicon.ico', '/favicon.svg') or request.method not in ('GET', 'HEAD')
            or not setup_flow.needs_setup()):
        return await call_next(request)
    return RedirectResponse(url='/setup', status_code=302)
