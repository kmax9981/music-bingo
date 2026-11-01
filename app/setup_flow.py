"""First run: until the first host account exists, every page sends the visitor to the setup screen (/setup), where they
create the admin account and can enter the public address and Spotify developer app details."""

from . import models, settings
from .common import _bootstrap_admin_user
from .db import SessionLocal

_done = False


def needs_setup() -> bool:
    """True while there is no host account at all. (Once there is one this stays False without asking the database again.)"""
    global _done
    if _done:
        return False
    db = SessionLocal()
    try:
        if db.query(models.HostUser).count() > 0:
            _done = True
            return False
        return True
    except Exception:
        return False   # tables not ready: do not lock everybody out into a setup screen that cannot work either
    finally:
        db.close()


def finished() -> None:
    global _done
    _done = True


def startup() -> None:
    """Called once when the app starts."""
    db = SessionLocal()
    try:
        _bootstrap_admin_user(db)   # unattended install with HOST_ADMIN_PASSWORD
    finally:
        db.close()
    from .version import VERSION
    print(f"Music Bingo {VERSION}", flush=True)
    if needs_setup():
        print(f"SETUP: no host account exists yet. Open {settings.public_base()}/setup to create the admin account.", flush=True)
