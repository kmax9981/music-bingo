"""Best-effort steps: things that must never break a request (a rollback, a live-update broadcast, a courtesy Spotify
call) but should not fail silently either. `with best_effort():` swallows any Exception, exactly like
`try: ... except Exception: pass` did, and writes one line to the log the first time each place fails
(file, line and exception type), so a step that is quietly broken shows up in `docker logs` once instead of never."""
import contextlib
import os
import traceback

_SEEN = set()


def _where(exc: BaseException):
    tb = traceback.extract_tb(exc.__traceback__)
    frame = tb[-1] if tb else None
    if frame is None:
        return ('?', 0, '?')
    # the innermost frame inside this app (library frames below it say less than the line in our code)
    for fr in reversed(tb):
        if os.sep + 'app' + os.sep in fr.filename or fr.filename.startswith('app' + os.sep):
            frame = fr
            break
    return (os.path.basename(frame.filename), frame.lineno, frame.name)


def log_swallowed(exc: BaseException) -> None:
    """One log line per (file, line, exception type) for the life of the process."""
    try:
        f, line, func = _where(exc)
        key = (f, line, type(exc).__name__)
        if key in _SEEN:
            return
        _SEEN.add(key)
        print(f"SWALLOWED {f}:{line} in {func}: {type(exc).__name__}: {str(exc)[:160]}", flush=True)
    except Exception:
        pass


@contextlib.contextmanager
def best_effort():
    try:
        yield
    except Exception as e:
        log_swallowed(e)


def rollback_quietly(db) -> None:
    """Roll back after a failed write; if even that fails there is nothing more to do."""
    with best_effort():
        db.rollback()
