"""Emergency password reset, run from a shell on the server (there is no web endpoint for this):

    docker exec -it bingo-dev python -m app.reset_password USERNAME            # new random password, shown once
    docker exec -it bingo-dev python -m app.reset_password USERNAME --create   # create the user (as admin) if missing

Whoever can run this already controls the server, so no extra secret is needed or stored."""
import sys

from . import models
from .db import SessionLocal
from .passwords import pw_hash, random_password


def main(argv) -> int:
    args = [a for a in argv if not a.startswith('--')]
    create = '--create' in argv
    if len(args) != 1:
        print(__doc__)
        return 2
    username = args[0].strip()
    db = SessionLocal()
    try:
        u = db.query(models.HostUser).filter(models.HostUser.username == username).first()
        if not u and not create:
            print(f"No user named {username!r}. Add --create to create it as an admin.")
            return 1
        password = random_password()
        if not u:
            u = models.HostUser(username=username, password_hash=pw_hash(password), is_admin=True, must_change_password=True)
            db.add(u)
        else:
            u.password_hash = pw_hash(password)
            u.must_change_password = True
        db.commit()
        print(f"Password for {username!r} is now: {password}")
        print("Log in with it: you will be asked to choose your own password straight away.")
        return 0
    finally:
        db.close()


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
