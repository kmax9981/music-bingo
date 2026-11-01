import os
import secrets
from itsdangerous import URLSafeTimedSerializer, BadData

# A missing secret used to fall back to a public placeholder, which let anyone forge an admin cookie.
_PLACEHOLDER = 'dev-secret-change-me'


def _load_cookie_secret() -> str:
    """COOKIE_SECRET from the environment, or (when it is not set) a random one made on first start and kept in the data
    folder, so a plain `docker compose up` needs no secrets to be written by hand. It must stay the same between starts:
    it signs session cookies and the check codes on printed paper cards."""
    env = (os.environ.get('COOKIE_SECRET') or '').strip()
    if env == _PLACEHOLDER:
        raise RuntimeError('COOKIE_SECRET is the placeholder; refusing to start')
    if env:
        return env
    path = os.path.join(os.environ.get('BINGO_DATA_DIR') or '/data', 'cookie_secret')
    try:
        with open(path, encoding='utf-8') as f:
            saved = f.read().strip()
        if saved:
            return saved
    except PermissionError as e:
        raise RuntimeError(f'{path} exists but the app cannot read it (a restored copy is owned by root). Fix with: '
                           'docker compose run --rm -u root --entrypoint chown app bingo /data/cookie_secret') from e
    except OSError:
        pass
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)   # readable only by the app
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            f.write(secrets.token_urlsafe(48))
    except FileExistsError:
        pass   # another process made it a moment ago: read it below
    except OSError as e:
        raise RuntimeError(f'COOKIE_SECRET is not set and no secret can be kept in {os.path.dirname(path)} ({e}); '
                           'set COOKIE_SECRET or mount a writable data folder') from e
    with open(path, encoding='utf-8') as f:
        return f.read().strip()


COOKIE_SECRET = _load_cookie_secret()

# Signed cookies carry a timestamp and expire server-side, so a stolen cookie stops working.
# Matches the 7-day cookie lifetime set in main.set_cookie().
MAX_AGE_SECONDS = 7 * 86400
serializer = URLSafeTimedSerializer(COOKIE_SECRET, salt='bingo-cookie-v2')

def sign(data: dict) -> str:
    return serializer.dumps(data)

def unsign(token: str, max_age: int = MAX_AGE_SECONDS) -> dict | None:
    try:
        return serializer.loads(token, max_age=max_age)
    except BadData:
        return None
