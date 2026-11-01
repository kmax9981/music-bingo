"""Response hardening shared by every page: secure cookie flags, security headers and the content security policy,
plus the safe-redirect check used after login. No imports from the rest of the app, so it can be read on its own."""
import secrets


def harden_set_cookie_headers(request, response):
    """
    Normalizes & hardens Set-Cookie headers to address scanner findings:
      - Fix "Missing Value": ensure cookie has name=value form (insert '=' if missing).
      - Add HttpOnly.
      - Add SameSite=Lax if absent.
      - Add Path=/ if absent.
      - Add Secure *only when request is https* (X-Forwarded-Proto or request.url.scheme).
    """
    try:
        raw = list(getattr(response, "raw_headers", []) or [])
    except Exception:
        return

    # Determine if request is HTTPS (behind proxy uses X-Forwarded-Proto)
    try:
        xf = (request.headers.get("x-forwarded-proto") or "").lower()
    except Exception:
        xf = ""
    try:
        scheme = (getattr(getattr(request, "url", None), "scheme", "") or "").lower()
    except Exception:
        scheme = ""
    is_https = (xf == "https") or (scheme == "https")

    new_raw = []
    set_cookie_seen = False

    for k, v in raw:
        if k.lower() != b"set-cookie":
            new_raw.append((k, v))
            continue

        set_cookie_seen = True
        try:
            sc = v.decode("latin-1")
        except Exception:
            new_raw.append((k, v))
            continue

        parts = [p.strip() for p in sc.split(";") if p is not None]
        if not parts:
            new_raw.append((k, v))
            continue

        first = parts[0]

        # Fix "Missing Value": if first token has no '=' (e.g. "cookieName"), add "=" with empty value
        if "=" not in first:
            first = first + "="

        cname = first.split("=", 1)[0].strip()
        attrs = parts[1:]

        def has_attr(prefix: str) -> bool:
            pref = prefix.lower()
            for a in attrs:
                al = a.lower()
                if al == pref or al.startswith(pref + "="):
                    return True
            return False

        if not has_attr("path"):
            attrs.append("Path=/")

        if not has_attr("samesite"):
            attrs.append("SameSite=Lax")

        if not has_attr("httponly"):
            attrs.append("HttpOnly")

        if is_https and not has_attr("secure"):
            attrs.append("Secure")

        # __Host- cookies must not include Domain=
        if cname.startswith("__Host-"):
            attrs = [a for a in attrs if not a.lower().startswith("domain=")]
            if is_https and not has_attr("secure"):
                attrs.append("Secure")

        if cname.startswith("__Secure-") and is_https and not has_attr("secure"):
            attrs.append("Secure")

        hardened = "; ".join([first] + attrs)
        new_raw.append((k, hardened.encode("latin-1")))

    if set_cookie_seen:
        try:
            response.raw_headers = new_raw
        except Exception:
            pass


def safe_next_path(nxt: str) -> str:
    """Allow only relative in-site paths like /host or /play. Fallback to /home (the Host / Join / Play Alone chooser)."""
    try:
        nxt = (nxt or '').strip()
        if not nxt:
            return '/home'
        if not nxt.startswith('/'):
            return '/home'
        if nxt.startswith('//'):
            return '/home'
        if '\\' in nxt:
            return '/home'
        return nxt
    except Exception:
        return '/home'


async def security_headers_middleware(request, call_next):
    # Fresh random value per request: templates put it on their own <script> tags and the CSP only runs scripts that carry it
    nonce = secrets.token_urlsafe(18)
    request.state.csp_nonce = nonce
    resp = await call_next(request)

    # Missing-header scanner basics
    resp.headers["X-Content-Type-Options"] = resp.headers.get("X-Content-Type-Options", "nosniff")
    resp.headers["X-Frame-Options"] = resp.headers.get("X-Frame-Options", "DENY")

    # HSTS only when actually HTTPS (Cloudflare/reverse proxy sets X-Forwarded-Proto)
    proto = (request.headers.get("x-forwarded-proto") or request.url.scheme or "").lower()
    if proto == "https":
        resp.headers["Strict-Transport-Security"] = resp.headers.get(
            "Strict-Transport-Security",
            "max-age=31536000; includeSubDomains"
        )

    # Scripts must be files from this site, the Spotify/Cloudflare hosts below, or inline scripts carrying this request's nonce.
    # Styles must be files from this site: no inline <style> blocks or style="" attributes (el.style.x = ... from a script is fine).
    if "Content-Security-Policy" not in resp.headers:
        secure = proto == "https"
        resp.headers["Content-Security-Policy"] = " ".join([
            "default-src 'self';",
            "base-uri 'self';",
            "object-src 'none';",
            "frame-ancestors 'none';",
            "form-action 'self';",
            "img-src 'self' data: https:;",
            "style-src 'self';",
            f"script-src 'self' 'nonce-{nonce}' https://sdk.scdn.co https://static.cloudflareinsights.com;",
            # Over plain http (an install on your own computer or network) the live-update socket is ws://, which Safari does not
            # count as "'self'", so it is named; over https wss: is already allowed.
            f"connect-src 'self' https: wss: {'' if secure else 'ws: '}https://api.spotify.com https://accounts.spotify.com https://*.spotify.com;",
            "frame-src https: https://accounts.spotify.com https://open.spotify.com;",
            # Only for pages served over https: on a plain-http address it would make browsers (Safari, and any browser on a
            # network address) fetch the page's own files over https, which this server does not speak, and the page would be blank
            "upgrade-insecure-requests;" if secure else "",
        ]).strip()


# Set modern security headers (scan hardening)
    # Referrer policy
    resp.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    # Permissions policy (disable common powerful features by default)
    resp.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(), payment=(), usb=()"
    # Legacy XSS protection header (modern browsers ignore; set to 0 intentionally)
    resp.headers["X-XSS-Protection"] = "0"

    # Cross-origin isolation related headers
    # COOP: keep strong default while still allowing OAuth/popups to function
    resp.headers["Cross-Origin-Opener-Policy"] = "same-origin-allow-popups"
    # COEP: explicitly set (unsafe-none avoids breaking 3rd-party iframes/resources)
    resp.headers["Cross-Origin-Embedder-Policy"] = "unsafe-none"
    # CORP: prevent other sites from loading our resources in a cross-origin context
    resp.headers["Cross-Origin-Resource-Policy"] = "same-site"

    # Harden Set-Cookie flags when cookies are emitted (HttpOnly/Secure/SameSite).
    # Starlette can emit multiple Set-Cookie headers; we preserve them all.
    try:
        cookies = resp.headers.getlist("set-cookie")
    except Exception:
        cookies = []
    if cookies:
        # Clear existing set-cookie entries
        try:
            del resp.headers["set-cookie"]
        except Exception:
            pass

        def _harden_cookie(sc: str) -> str:
            s = sc
            low = s.lower()
            if "httponly" not in low:
                s += "; HttpOnly"
                low = s.lower()
            if "samesite" not in low:
                # Lax is a reasonable default that avoids breaking common flows
                s += "; SameSite=Lax"
                low = s.lower()
            # Only set Secure when we are on HTTPS (or behind proxy reporting https)
            scheme = (request.headers.get("x-forwarded-proto") or request.url.scheme or "").lower()
            if scheme == "https" and "secure" not in low:
                s += "; Secure"
            return s

        for sc in cookies:
            resp.headers.append("set-cookie", _harden_cookie(sc))

        # Cookie hardening (scanner fixes)
        harden_set_cookie_headers(request, resp)

    return resp
