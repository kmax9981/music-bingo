"""Failed-login throttling (in-process; this app runs a single uvicorn worker): 5 wrong passwords per visitor and
username, or 20 per visitor, within 15 minutes; the emergency-reset token has its own limit."""
import os
import threading
import time

from fastapi import Request

# Requests arrive via Cloudflare, so the socket peer is always the docker gateway; the visitor IP
# Cloudflare forwards is used instead (default). Set TRUST_PROXY_HEADERS=false if the app is ever reached
# without the proxy, because anyone could then send a fake header (the socket peer is used, and behind a
# proxy that makes all visitors share one IP).
_LOGIN_WINDOW_S = 15 * 60
_LOGIN_LIMITS = {"ip_user": 5, "ip": 20}
_LOGIN_FAILS = {}
_LOGIN_FAILS_LOCK = threading.Lock()

TRUST_PROXY_HEADERS = os.environ.get('TRUST_PROXY_HEADERS', 'true').strip().lower() not in ('0', 'false', 'no', 'off')

def client_ip(request: Request) -> str:
    ip = ''
    if TRUST_PROXY_HEADERS:
        ip = (request.headers.get("cf-connecting-ip") or "").strip()
        if not ip:
            ip = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
    if not ip and request.client:
        ip = request.client.host
    return ip or "unknown"

def login_keys(request: Request, username: str):
    ip = client_ip(request)
    return [("ip_user", ip, (username or "").strip().lower()), ("ip", ip)]

def login_blocked(keys) -> bool:
    now = time.monotonic()
    with _LOGIN_FAILS_LOCK:
        for k in keys:
            fails = [t for t in _LOGIN_FAILS.get(k, []) if now - t < _LOGIN_WINDOW_S]
            _LOGIN_FAILS[k] = fails
            if len(fails) >= _LOGIN_LIMITS[k[0]]:
                return True
    return False

def login_failed(keys) -> None:
    now = time.monotonic()
    with _LOGIN_FAILS_LOCK:
        for k in keys:
            _LOGIN_FAILS.setdefault(k, []).append(now)

def login_succeeded(keys) -> None:
    with _LOGIN_FAILS_LOCK:
        for k in keys:
            if k[0] == "ip_user":
                _LOGIN_FAILS.pop(k, None)

LOGIN_BLOCKED_MSG = "Too many failed attempts. Please wait 15 minutes and try again."
