"""Host passwords: PBKDF2-HMAC-SHA256 hashes, and random password generation for first-run and reset-from-the-shell.
Format: pbkdf2$<iterations>$<salt_b64>$<hash_b64>"""
import base64
import hashlib
import hmac
import os
import secrets


def pw_hash(password: str, iterations: int = 200000) -> str:
    pw = (password or "").encode("utf-8", "ignore")
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", pw, salt, iterations, dklen=32)
    return "pbkdf2$%d$%s$%s" % (
        iterations,
        base64.urlsafe_b64encode(salt).decode("ascii").rstrip("="),
        base64.urlsafe_b64encode(dk).decode("ascii").rstrip("="),
    )


def pw_verify(password: str, stored: str) -> bool:
    try:
        parts = (stored or "").split("$")
        if len(parts) != 4 or parts[0] != "pbkdf2":
            return False
        it = int(parts[1])
        salt = base64.urlsafe_b64decode(parts[2] + "==")
        good = base64.urlsafe_b64decode(parts[3] + "==")
        pw = (password or "").encode("utf-8", "ignore")
        dk = hashlib.pbkdf2_hmac("sha256", pw, salt, it, dklen=len(good))
        return hmac.compare_digest(dk, good)
    except Exception:
        return False


def random_password(n: int = 16) -> str:
    """Letters and digits without look-alikes (no 0/O, 1/l/I), easy to read off a screen and type."""
    alphabet = 'ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz23456789'
    return ''.join(secrets.choice(alphabet) for _ in range(n))
