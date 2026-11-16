"""Checks for the optional single sign-in helpers (app/oidc.py). No server, database or network needed:
    python3 tests/test_oidc.py
"""
import base64
import hashlib
import importlib.util
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location('oidc', os.path.join(HERE, '..', 'app', 'oidc.py'))
oidc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(oidc)

ENV = ('OIDC_ENABLED', 'OIDC_ISSUER', 'OIDC_CLIENT_ID', 'OIDC_CLIENT_SECRET', 'OIDC_PROVIDER_NAME', 'OIDC_USERNAME_CLAIM', 'OIDC_HIDE_LOCAL_LOGIN')


def clear():
    for k in ENV:
        os.environ.pop(k, None)


def check(name, cond):
    print(('ok   ' if cond else 'FAIL ') + name)
    if not cond:
        check.failed += 1


check.failed = 0

clear()
check('off when nothing is set', not oidc.enabled())
os.environ.update(OIDC_ISSUER='https://id.example.com/app/', OIDC_CLIENT_ID='bingo')
check('still off without the secret', not oidc.enabled())
os.environ['OIDC_CLIENT_SECRET'] = 'x'
check('on when issuer, id and secret are set', oidc.enabled())
check('switch defaults to on', not oidc.switched_off())
os.environ['OIDC_ENABLED'] = 'false'
check('switched off keeps the settings but disables the sign-in', oidc.configured() and not oidc.enabled() and not oidc.hide_local())
os.environ['OIDC_ENABLED'] = 'true'
check('switched on again', oidc.enabled())
os.environ.pop('OIDC_ENABLED')
check('default button text', oidc.provider_name() == 'Single sign-in')
os.environ['OIDC_PROVIDER_NAME'] = 'Example login'
check('custom button text', oidc.provider_name() == 'Example login')
check('local login shown by default', not oidc.hide_local())
os.environ['OIDC_HIDE_LOCAL_LOGIN'] = 'true'
check('local login hidden when asked', oidc.hide_local())
clear()
os.environ['OIDC_HIDE_LOCAL_LOGIN'] = 'true'
check('hide flag does nothing while sign-in is off', not oidc.hide_local())

clear()
check('the user name is the provider name, unchanged', oidc.local_username({'preferred_username': 'mattlnew'}) == 'mattlnew')
check('no claim gives nothing', oidc.local_username({}) == '')
os.environ['OIDC_USERNAME_CLAIM'] = 'email'
check('other claim', oidc.local_username({'email': 'person@example.com'}) == 'person@example.com')

v, c = oidc.pkce_pair()
expect = base64.urlsafe_b64encode(hashlib.sha256(v.encode()).digest()).decode().rstrip('=')
check('pkce challenge matches the verifier', c == expect and len(v) >= 43 and '=' not in c)
check('pkce pairs are random', oidc.pkce_pair()[0] != oidc.pkce_pair()[0])

clear()
os.environ.update(OIDC_ISSUER='https://id.example.com/app/', OIDC_CLIENT_ID='bingo', OIDC_CLIENT_SECRET='x')
oidc._DISCOVERY.update(at=__import__('time').time(), data={'authorization_endpoint': 'https://id.example.com/authorize/'})
url = oidc.authorize_url('https://bingo.example.com/auth/oidc/callback', 'STATE1', 'CHAL1')
check('authorize url carries state, challenge and S256', url.startswith('https://id.example.com/authorize/?') and 'state=STATE1' in url
      and 'code_challenge=CHAL1' in url and 'code_challenge_method=S256' in url and 'client_id=bingo' in url)
check('authorize url asks for the code flow', 'response_type=code' in url and 'scope=openid+profile+email' in url)

clear()
print('\n%s' % ('all checks passed' if not check.failed else '%d check(s) failed' % check.failed))
sys.exit(1 if check.failed else 0)
