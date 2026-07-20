"""Two-tier, disk-backed image cache: small thumbnails for the strip/grid,
larger previews for the main cull view. Kept as separate directories, per
SESSION-FLOW.md §7 — a grid re-tiling shouldn't have to wait on preview-sized
files, and vice versa.

Generation never blocks the caller: CacheManager.request() returns the cached
path immediately if it already exists, otherwise queues the work and returns
None. The queue is priority-ordered so callers can ask for the photo nearest
the user's current position to be generated first.
"""

import io
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
import traceback

from PIL import Image, ImageOps

import exiftool_path

CACHE_ROOT = os.path.expanduser('~/Library/Application Support/Winnow/cache')

# kind -> (subdirectory, long-edge px)
SIZES = {
    'thumbnail': (os.path.join(CACHE_ROOT, 'thumbnails'), 200),
    'preview': (os.path.join(CACHE_ROOT, 'previews'), 2000),
}

FULL_DIR = os.path.join(CACHE_ROOT, 'full')


def ensure_local_full_copy(record, log=None):
    """Zoom past fit wants the source JPEG at full resolution. Confirmed by
    direct reproduction (mount a real disk image under /Volumes/, try to
    load a file:// image from it): the main Python process can read a file
    on a removable volume (SD card) just fine, but WKWebView's renderer
    process cannot load a file:// resource from one at all — it fires
    'error' immediately. Pointing <img src> straight at the source on the
    card, as the first version of this did, meant zoom could never work off
    a real card at all. So: copy the JPEG into local cache once per photo
    (atomic temp-then-rename, skip if an identically-sized copy already
    exists — same pattern as output.py's file copies) and always serve
    zoom from there instead."""

    def _log(msg):
        if log:
            log(msg)

    jpg = record.get('jpg_path')
    if not jpg:
        return None
    identity = record['identity']
    dest = os.path.join(FULL_DIR, f'{identity}.jpg')

    src_size = os.path.getsize(jpg)
    if os.path.exists(dest) and os.path.getsize(dest) == src_size:
        _log(f'ensure_local_full_copy: already cached locally at {dest}')
        return dest

    _log(f'ensure_local_full_copy: copying {jpg} ({src_size} bytes) -> local cache')
    t0 = time.monotonic()
    os.makedirs(FULL_DIR, exist_ok=True)
    tmp = dest + f'.tmp-{os.getpid()}'
    try:
        shutil.copyfile(jpg, tmp)
        copied_size = os.path.getsize(tmp)
        if copied_size != src_size:
            raise IOError(f'copied size {copied_size} != source size {src_size}')
        os.replace(tmp, dest)
    except Exception:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise
    _log(f'ensure_local_full_copy: copy finished in {(time.monotonic()-t0)*1000:.0f}ms -> {dest}')
    return dest


def cache_path(identity, kind):
    directory, _ = SIZES[kind]
    return os.path.join(directory, f'{identity}.jpg')


def is_cached(identity, kind):
    return os.path.exists(cache_path(identity, kind))


def _log(msg):
    print(f'[cache] {msg}', file=sys.stderr, flush=True)


def _source_bytes(record):
    """Bytes to decode: the JPEG if this pair has one, else the embedded
    preview pulled out of the ORF. Returns None if neither is available —
    logging exactly why, since a silent None here is what used to show up
    as a permanently blank thumbnail with nothing in the terminal."""
    identity = record.get('identity')
    jpg = record.get('jpg_path')
    if jpg:
        with open(jpg, 'rb') as f:
            return f.read()

    raw = record.get('raw_path')
    if not raw:
        _log(f'{identity}: no jpg_path and no raw_path — nothing to read')
        return None

    exiftool_bin, _version = exiftool_path.resolve()
    if not exiftool_bin:
        _log(f'{identity}: exiftool not found, cannot extract embedded preview from {raw}')
        return None

    cmd = [exiftool_bin, '-b', '-PreviewImage', raw]
    result = subprocess.run(cmd, capture_output=True)
    if result.stdout:
        return result.stdout
    _log(
        f"{identity}: '{' '.join(cmd)}' produced no PreviewImage data "
        f'(exit {result.returncode}, stderr: {result.stderr.decode(errors="replace").strip()})'
    )
    return None


def generate(record, kind):
    """Build (or reuse) the cached file for `record` at the given kind.
    Returns the path, or None if no source image could be read (already
    logged by _source_bytes) or decoding/resizing/saving raised — that
    exception propagates to the caller, which is responsible for logging
    it with full context and reporting the failure onward."""
    directory, long_edge = SIZES[kind]
    dest = cache_path(record['identity'], kind)
    if os.path.exists(dest):
        return dest

    data = _source_bytes(record)
    if not data:
        return None

    os.makedirs(directory, exist_ok=True)
    img = Image.open(io.BytesIO(data))
    img = ImageOps.exif_transpose(img)  # OM-1 portrait frames carry an orientation tag
    img = img.convert('RGB')
    w, h = img.size
    scale = long_edge / max(w, h)
    if scale < 1:  # never upscale a source smaller than the target
        img = img.resize((max(1, round(w * scale)), max(1, round(h * scale))), Image.LANCZOS)

    tmp = dest + f'.tmp-{os.getpid()}'
    img.save(tmp, 'JPEG', quality=88)
    os.replace(tmp, dest)  # atomic — a concurrent reader never sees a partial file
    return dest


class CacheManager:
    """Background generation queue. `on_ready(identity, kind, path)` fires
    from a worker thread once a job finishes — `path` is None on failure
    (source unreadable, or an exception during decode/resize/save), so the
    caller can tell the front-end to show a visible failed state rather
    than leaving a thumbnail blank forever with no signal anywhere."""

    def __init__(self, on_ready=None, workers=4):
        self._on_ready = on_ready
        self._queue = queue.PriorityQueue()
        self._pending = {}  # (identity, kind) -> best priority queued so far
        self._lock = threading.Lock()
        self._seq = 0
        for _ in range(workers):
            threading.Thread(target=self._worker, daemon=True).start()

    def request(self, record, kind, priority=0):
        """Return the cached path if it already exists. Otherwise enqueue
        generation and return None. A second request for the same
        identity/kind is a no-op unless it asks for a better (lower)
        priority than what's already queued — e.g. a photo that was
        prefetched as a neighbour and has since become the current one —
        in which case it's pushed again so it jumps the queue. The stale
        lower-priority entry, when it's eventually popped, becomes a cheap
        no-op: generate() sees the file already exists."""
        dest = cache_path(record['identity'], kind)
        if os.path.exists(dest):
            return dest
        key = (record['identity'], kind)
        with self._lock:
            best = self._pending.get(key)
            if best is not None and priority >= best:
                return None
            self._pending[key] = priority
            self._seq += 1
            self._queue.put((priority, self._seq, record, kind))
        return None

    def _worker(self):
        while True:
            priority, seq, record, kind = self._queue.get()
            identity = record.get('identity')
            try:
                path = generate(record, kind)
            except Exception:
                _log(f'{identity} ({kind}): generate() raised —\n{traceback.format_exc()}')
                path = None
            with self._lock:
                self._pending.pop((identity, kind), None)
            if self._on_ready:
                self._on_ready(identity, kind, path)  # path is None on failure — caller must handle that
            self._queue.task_done()
