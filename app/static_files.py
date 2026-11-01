"""The /static files. Templates link to them with static_url(), which adds a version taken from the file's content, so a
changed file gets a new address and browsers may keep every versioned file for a year without asking again."""
import hashlib
from pathlib import Path

from fastapi.staticfiles import StaticFiles

STATIC_DIR = Path('app/static')
_versions = {}   # path -> (modified time, short content hash)


def static_url(path: str) -> str:
    f = STATIC_DIR / path
    try:
        mtime = f.stat().st_mtime
    except OSError:
        return '/static/' + path
    cached = _versions.get(path)
    if not cached or cached[0] != mtime:
        cached = _versions[path] = (mtime, hashlib.sha1(f.read_bytes()).hexdigest()[:10])
    return f'/static/{path}?v={cached[1]}'


class CachedStaticFiles(StaticFiles):
    def file_response(self, full_path, stat_result, scope, status_code=200):
        resp = super().file_response(full_path, stat_result, scope, status_code)
        versioned = b'v=' in scope.get('query_string', b'')
        resp.headers['Cache-Control'] = 'public, max-age=31536000, immutable' if versioned else 'no-cache'   # no-cache: ask, answered by a short 304
        return resp
