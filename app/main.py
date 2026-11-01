"""Music Bingo web app: creates the FastAPI app, the security middleware and the static files, then includes the
route modules in app/routes/. Shared helpers live next to this file (common.py, cards.py, playlists.py, paper.py, ...)."""
import logging
import re

from fastapi import FastAPI, Depends
from .static_files import CachedStaticFiles

from .csrf import CsrfFailed, csrf_guard, csrf_cookie_middleware, csrf_failed_handler
from .http_headers import security_headers_middleware

_ONE_TIME_QUERY = re.compile(r'([?&](?:code|state|error_description)=)[^&\s"]*')
_COHOST_PATH = re.compile(r'(/cohost/[A-Za-z0-9]+/)[A-Za-z0-9_-]+')


class _RedactOneTimeValues(logging.Filter):
    """The Spotify sign-in redirect carries a one-time code and a state value in its address, and a co-host link carries its
    secret: keep them out of the access log."""
    def filter(self, record):
        if isinstance(record.args, tuple):
            record.args = tuple(_COHOST_PATH.sub(r'\1[redacted]', _ONE_TIME_QUERY.sub(r'\1[redacted]', a)) if isinstance(a, str) else a for a in record.args)
        return True


logging.getLogger('uvicorn.access').addFilter(_RedactOneTimeValues())

app = FastAPI(dependencies=[Depends(csrf_guard)])
app.middleware("http")(csrf_cookie_middleware)   # per-browser CSRF cookie + token for templates (added first so the headers middleware wraps it)
app.add_exception_handler(CsrfFailed, csrf_failed_handler)
app.middleware("http")(security_headers_middleware)   # security headers, CSP and cookie flags on every response
app.mount('/static', CachedStaticFiles(directory='app/static'), name='static')

from . import migrations  # noqa: E402,F401  (creates the tables and applies the column migrations while it is imported)
from . import themes  # noqa: E402,F401  (registers theme_of() for the templates)
from . import setup_flow  # noqa: E402
from .routes import home, solo, player, auth, host_games, playlist_pages, spotify_account, game_live, game_playback, game_claims, paper_pages, setup, cohost  # noqa: E402

setup_flow.startup()   # unattended install from HOST_ADMIN_PASSWORD, or send visitors to the first-run screen
app.middleware("http")(setup.setup_redirect_middleware)   # no host account yet: every page goes to /setup

for _module in (home, solo, player, auth, host_games, playlist_pages, spotify_account, game_live, game_playback, game_claims, paper_pages, setup, cohost):
    app.include_router(_module.router)

# Used by the test server and tools that import this module
from .db import SessionLocal  # noqa: E402,F401
from .passwords import pw_hash as _pw_hash  # noqa: E402,F401
from .common import _bootstrap_admin_user  # noqa: E402,F401
