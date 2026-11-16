"""Optional single sign-in (OpenID Connect) for the host login. Players never sign in, so none of this touches them.

Off unless OIDC_ISSUER, OIDC_CLIENT_ID and OIDC_CLIENT_SECRET are all set, either in the environment or on the Admin page (Host Admin >
Single sign-in; a value in the environment wins, as with the other settings); with it off the app behaves exactly as before. Settings:

  OIDC_ISSUER              address of the identity provider, for example https://login.example.com/application/o/bingo/
  OIDC_CLIENT_ID           the client id registered for this app
  OIDC_CLIENT_SECRET       the client secret
  OIDC_ENABLED             optional: false switches the sign-in off without losing the other settings (Admin page: the Turn on box)
  OIDC_PROVIDER_NAME       text on the button (default "Single sign-in")
  OIDC_USERNAME_CLAIM      which claim holds the user name (default preferred_username)
  OIDC_HIDE_LOCAL_LOGIN    true: the password form is not shown on the login page (it is still reachable at /login?local=1,
                           which is how the local emergency admin signs in)

The sign-in is the standard authorization code flow with PKCE. The identity of the person comes from the provider's userinfo
endpoint, called with the token the provider just handed over on a direct HTTPS connection, so no extra libraries are needed.
Nobody is created by a sign-in: the provider's user name must match an existing host account (rename the host account on the Admin or Account page if the names differ).
"""
import base64
import hashlib
import os
import secrets
import time

import requests

_DISCOVERY = {'at': 0.0, 'data': None}
_DISCOVERY_TTL = 3600
_TIMEOUT = 10


_getter = None   # the app installs settings.get here (environment first, then what the Admin page saved); tests use the environment


def use_settings(fn) -> None:
    global _getter
    _getter = fn


def _env(key: str) -> str:
    if _getter is not None:
        return (_getter(key) or '').strip()
    return (os.environ.get(key) or '').strip()


def forget_discovery() -> None:
    _DISCOVERY['data'] = None


def configured() -> bool:
    return bool(_env('OIDC_ISSUER') and _env('OIDC_CLIENT_ID') and _env('OIDC_CLIENT_SECRET'))


def switched_off() -> bool:
    """OIDC_ENABLED set to false/no/off/0 turns the sign-in off while keeping every setting. Not set means on (when configured)."""
    return _env('OIDC_ENABLED').lower() in ('0', 'false', 'no', 'off')


def enabled() -> bool:
    return configured() and not switched_off()


def provider_name() -> str:
    return _env('OIDC_PROVIDER_NAME') or 'Single sign-in'


def hide_local() -> bool:
    return enabled() and _env('OIDC_HIDE_LOCAL_LOGIN').lower() in ('1', 'true', 'yes', 'on')


def username_claim() -> str:
    return _env('OIDC_USERNAME_CLAIM') or 'preferred_username'


def local_username(claims: dict) -> str:
    """The Bingo host user name a provider identity maps to ('' when the identity carries none)."""
    name = str((claims or {}).get(username_claim()) or '').strip()
    if not name:
        return ''
    return name


def pkce_pair() -> tuple:
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
    return verifier, challenge


def discovery() -> dict:
    now = time.time()
    if _DISCOVERY['data'] is None or now - _DISCOVERY['at'] > _DISCOVERY_TTL:
        url = _env('OIDC_ISSUER').rstrip('/') + '/.well-known/openid-configuration'
        r = requests.get(url, timeout=_TIMEOUT)
        r.raise_for_status()
        _DISCOVERY['data'], _DISCOVERY['at'] = r.json(), now
    return _DISCOVERY['data']


def authorize_url(redirect_uri: str, state: str, challenge: str) -> str:
    from urllib.parse import urlencode
    q = {'response_type': 'code', 'client_id': _env('OIDC_CLIENT_ID'), 'redirect_uri': redirect_uri, 'scope': 'openid profile email',
         'state': state, 'code_challenge': challenge, 'code_challenge_method': 'S256'}
    return discovery()['authorization_endpoint'] + '?' + urlencode(q)


def claims_for_code(code: str, redirect_uri: str, verifier: str) -> dict:
    """Trade the one-time code for a token and read who it belongs to. Raises on any failure."""
    d = discovery()
    tr = requests.post(d['token_endpoint'], data={'grant_type': 'authorization_code', 'code': code, 'redirect_uri': redirect_uri,
                                                  'client_id': _env('OIDC_CLIENT_ID'), 'client_secret': _env('OIDC_CLIENT_SECRET'),
                                                  'code_verifier': verifier}, timeout=_TIMEOUT)
    tr.raise_for_status()
    token = tr.json().get('access_token')
    if not token:
        raise RuntimeError('the provider sent no access token')
    ur = requests.get(d['userinfo_endpoint'], headers={'Authorization': 'Bearer ' + token}, timeout=_TIMEOUT)
    ur.raise_for_status()
    return ur.json()


def end_session_url() -> str:
    try:
        return discovery().get('end_session_endpoint') or ''
    except Exception:
        return ''
