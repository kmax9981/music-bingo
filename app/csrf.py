"""CSRF protection. Every browser gets a random per-browser cookie (bingo_csrf, HttpOnly, SameSite=Lax); the token put
in pages and forms is an HMAC of that cookie value, so a forged cross-site request can neither read nor guess it, and a
cookie planted from elsewhere can't produce a matching token. Every state-changing request (POST, PUT, PATCH, DELETE)
must carry the token: in the form field "csrf_token", or in the X-CSRF-Token header (static/csrf.js adds it to the
page's own fetch() calls). The request's Origin/Referer must also be this site, and WebSocket handshakes from other
sites are refused."""
import base64
import hashlib
import hmac
import re
import secrets
from urllib.parse import urlparse

from fastapi import Request, WebSocket, WebSocketException
from fastapi.responses import HTMLResponse, JSONResponse

from .security import COOKIE_SECRET
from . import settings

CSRF_COOKIE = 'bingo_csrf'
CSRF_SAFE_METHODS = {'GET', 'HEAD', 'OPTIONS', 'TRACE'}
CSRF_EXEMPT_PATHS = set()   # paths that are not called from a browser page would go here
_CSRF_RAW_RE = re.compile(r'^[A-Za-z0-9_-]{20,80}$')


class CsrfFailed(Exception):
    pass


def csrf_token_for(raw: str) -> str:
    mac = hmac.new(COOKIE_SECRET.encode(), b'csrf|' + raw.encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(mac).decode().rstrip('=')


def _origin_allowed(origin: str, headers) -> bool:
    """True if this Origin/Referer URL is this site (the Host the browser used, a forwarded host, or PUBLIC_BASE_URL)."""
    try:
        host = (urlparse(origin).netloc or '').lower()
        if not host:
            return False
        ok = {(headers.get('host') or '').lower(), (headers.get('x-forwarded-host') or '').split(',')[0].strip().lower(),
              settings.public_host()}
        ok.discard('')
        return host in ok
    except Exception:
        return False


async def csrf_guard(request: Request = None, websocket: WebSocket = None):
    """Global dependency (runs for every route)."""
    if websocket is not None:  # a page on another site must not open this site's live-update sockets
        origin = websocket.headers.get('origin')
        if origin and not _origin_allowed(origin, websocket.headers):
            raise WebSocketException(code=1008)
        return
    if request is None or request.method in CSRF_SAFE_METHODS or request.url.path in CSRF_EXEMPT_PATHS:
        return
    origin = request.headers.get('origin') or ''
    if not origin:
        ref = request.headers.get('referer') or ''
        if ref:
            u = urlparse(ref)
            origin = f'{u.scheme}://{u.netloc}' if u.netloc else 'null'
    if origin and not _origin_allowed(origin, request.headers):
        raise CsrfFailed('origin')
    raw = request.cookies.get(CSRF_COOKIE, '')
    if not _CSRF_RAW_RE.match(raw):
        raise CsrfFailed('no cookie')
    submitted = request.headers.get('x-csrf-token') or ''
    if not submitted:
        ctype = (request.headers.get('content-type') or '').split(';')[0].strip().lower()
        if ctype in ('application/x-www-form-urlencoded', 'multipart/form-data'):
            form = await request.form()  # already parsed (and cached) when the route takes form fields
            submitted = str(form.get('csrf_token') or '')
    if not submitted or not hmac.compare_digest(submitted, csrf_token_for(raw)):
        raise CsrfFailed('token')


async def csrf_cookie_middleware(request, call_next):
    raw = request.cookies.get(CSRF_COOKIE, '')
    fresh = not _CSRF_RAW_RE.match(raw)
    if fresh:
        raw = secrets.token_urlsafe(32)
    request.state.csrf_token = csrf_token_for(raw)
    resp = await call_next(request)
    if fresh:
        proto = (request.headers.get('x-forwarded-proto') or request.url.scheme or '').lower()
        resp.set_cookie(CSRF_COOKIE, raw, httponly=True, secure=(proto == 'https'), samesite='lax', max_age=30 * 86400, path='/')
    return resp


async def csrf_failed_handler(request, exc):
    print(f"CSRF_REJECTED reason={exc} method={request.method} path={request.url.path}")
    msg = "Your session expired or this request didn't come from this site. Reload the page and try again."
    accept = (request.headers.get('accept') or '').lower()
    if 'application/json' in accept or (request.headers.get('content-type') or '').startswith('application/json') or request.headers.get('x-csrf-token'):
        return JSONResponse({'error': msg, 'csrf': True}, status_code=403)
    return HTMLResponse(
        '<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">'
        '<title>Please reload</title><body style="font-family:system-ui,sans-serif;background:#12142a;color:#eee;padding:32px;max-width:560px;margin:auto">'
        '<h2>Please reload the page</h2><p>' + msg + '</p><p><a style="color:#a78bfa" href="/">Back to the start</a></p></body>', status_code=403)
