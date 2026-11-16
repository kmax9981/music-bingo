"""Rules for renaming a host account (used by the Admin page and the Account page). Pure functions, no database."""
import os

MAX_LEN = 64


def reserved_admin() -> str:
    """The local emergency admin keeps its name (lower case). It is the account the first-run setup and the password reset tool create."""
    return (os.environ.get('HOST_ADMIN_USER') or 'admin').strip().lower()


def is_reserved(username: str) -> bool:
    return (username or '').strip().lower() == reserved_admin()


def check_new_username(new: str, current: str, existing_lower: set) -> tuple:
    """(clean name, '') when the rename is allowed, or ('', message in plain words).
    existing_lower: every host name in lower case. The account's own name is allowed to change case only."""
    clean = (new or '').strip()
    if not clean:
        return '', 'Type the new user name.'
    if len(clean) > MAX_LEN:
        return '', f'A user name can be at most {MAX_LEN} characters.'
    if any(ord(c) < 32 or ord(c) == 127 for c in clean):
        return '', 'A user name cannot contain control characters.'
    if is_reserved(current):
        return '', f'The local admin account keeps the name "{reserved_admin()}".'
    if is_reserved(clean):
        return '', f'"{clean}" is kept for the local admin account. Pick another name.'
    if clean == (current or ''):
        return '', 'That is already the name.'
    taken = set(existing_lower) - {(current or '').strip().lower()}
    if clean.lower() in taken:
        return '', f'There is already a host called "{clean}".'
    return clean, ''
