"""The release this app belongs to: app/VERSION says "dev" in the working copy, and tools/publish.sh writes the real
version number into it when a release is published."""
import os


def _read() -> str:
    try:
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'VERSION'), encoding='utf-8') as f:
            return f.read().strip() or 'dev'
    except OSError:
        return 'dev'


VERSION = _read()
