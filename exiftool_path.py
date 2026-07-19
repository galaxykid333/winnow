"""Resolves the exiftool binary once, robust to the PATH a double-clicked
.app gets from macOS — typically just /usr/bin:/bin:/usr/sbin:/sbin, which
does not include Homebrew's /opt/homebrew/bin (Apple Silicon) or
/usr/local/bin (Intel). A plain `subprocess.run(['exiftool', ...])` can
silently fail to find it under that PATH even though it works fine from a
terminal, where the shell profile has usually added Homebrew to PATH.

ingest.py and cache.py both shell out to exiftool; they should use resolve()
rather than the bare command name. api.py exposes the result to the
front-end's settings screen so this is visible without Console.app.
"""

import functools
import shutil
import subprocess

_HOMEBREW_CANDIDATES = [
    '/opt/homebrew/bin/exiftool',  # Apple Silicon Homebrew
    '/usr/local/bin/exiftool',     # Intel Homebrew
    '/usr/bin/exiftool',
]


@functools.lru_cache(maxsize=1)
def resolve():
    """Return (path, version) for the first working exiftool found, or
    (None, None) if none of the candidates run successfully."""
    found = shutil.which('exiftool')
    for path in ([found] if found else []) + _HOMEBREW_CANDIDATES:
        if not path:
            continue
        try:
            result = subprocess.run([path, '-ver'], capture_output=True, text=True, timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            continue
        if result.returncode == 0:
            return path, result.stdout.strip()
    return None, None


def require():
    """Like resolve(), but raises a clear error instead of returning None —
    for call sites where exiftool is not optional."""
    path, version = resolve()
    if not path:
        raise RuntimeError(
            "exiftool not found. Install it with 'brew install exiftool', "
            'then reopen Winnow (see Settings for the path currently resolved).'
        )
    return path, version
