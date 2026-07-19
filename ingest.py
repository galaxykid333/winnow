"""Scan an input folder for bird photos: read EXIF capture dates, pair
RAW+JPEG by filename stem, and group the result by capture date for the
calendar screen. No previews or thumbnails are generated here — see
cache.py, which runs later and only for the dates actually selected.
"""

import json
import os
import re
import subprocess
import threading
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Optional

import exiftool_path

RAW_EXTS = {'.orf'}
JPEG_EXTS = {'.jpg', '.jpeg'}
PHOTO_EXTS = RAW_EXTS | JPEG_EXTS

_PROGRESS_RE = re.compile(r'\[(\d+)/(\d+)\]\s*$')


@dataclass
class PhotoRecord:
    identity: str          # stable id: stem + capture second, see SESSION-FLOW.md §7
    stem: str
    jpg_path: Optional[str]
    raw_path: Optional[str]
    capture_dt: Optional[datetime]
    date_uncertain: bool   # True when capture_dt fell back to file mtime

    @property
    def date(self):
        return self.capture_dt.date() if self.capture_dt else None

    def to_dict(self):
        return {
            'identity': self.identity,
            'stem': self.stem,
            'jpg_path': self.jpg_path,
            'raw_path': self.raw_path,
            'capture_dt': self.capture_dt.isoformat() if self.capture_dt else None,
            'date_uncertain': self.date_uncertain,
            'has_raw_only': self.raw_path is not None and self.jpg_path is None,
        }


def _parse_exif_dt(value):
    if not value:
        return None
    try:
        return datetime.strptime(value[:19], '%Y:%m:%d %H:%M:%S')
    except ValueError:
        return None


def _make_identity(stem, dt):
    if dt:
        return f'{stem}_{dt.strftime("%Y%m%dT%H%M%S")}'
    return f'{stem}_unknown'


def scan_input_folder(folder: str, progress_cb: Optional[Callable[[int, int], None]] = None):
    """Recursively scan `folder`, one batched exiftool call, and return a
    list of PhotoRecord sorted by capture time ascending.

    `progress_cb(done, total)` is called as exiftool reports each file via
    its own -progress output on stderr, so the caller can show a real
    progress indicator without waiting for the whole scan to finish.
    """
    exiftool_bin, _version = exiftool_path.require()
    cmd = [
        exiftool_bin, '-progress', '-j', '-r',
        '-FileName', '-Directory',
        '-DateTimeOriginal', '-FileModifyDate',
        '--ext', 'xmp',  # never treat sidecar files as photos
        folder,
    ]
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )

    def _pump_stderr():
        for line in proc.stderr:
            m = _PROGRESS_RE.search(line)
            if m and progress_cb:
                progress_cb(int(m.group(1)), int(m.group(2)))

    stderr_thread = threading.Thread(target=_pump_stderr, daemon=True)
    stderr_thread.start()
    # Deliberately not proc.communicate(): it also reads stderr internally,
    # which races with _pump_stderr reading the same pipe and intermittently
    # raises "I/O operation on closed file". Reading stdout directly here
    # while the stderr thread drains stderr concurrently avoids both the
    # deadlock communicate() exists to prevent and that race.
    stdout = proc.stdout.read()
    proc.wait()
    stderr_thread.join()
    if proc.returncode not in (0, 1):  # exiftool returns 1 on partial errors
        raise RuntimeError(f'exiftool exited {proc.returncode} scanning {folder}')

    entries = json.loads(stdout) if stdout.strip() else []

    by_stem = {}
    for e in entries:
        name = e.get('FileName', '')
        stem, ext = os.path.splitext(name)
        ext = ext.lower()
        if ext not in PHOTO_EXTS:
            continue
        directory = e.get('Directory', folder)
        path = os.path.join(directory, name)
        key = (directory, stem.lower())
        group = by_stem.setdefault(key, {'stem_display': stem})

        if ext in RAW_EXTS:
            group['raw'] = path
        else:
            group['jpg'] = path

        dt = _parse_exif_dt(e.get('DateTimeOriginal'))
        if dt:
            group['dt'] = dt
            group['uncertain'] = False
        elif 'dt' not in group:
            mtime = _parse_exif_dt(e.get('FileModifyDate'))
            if mtime:
                group['dt'] = mtime
                group['uncertain'] = True

    records = []
    for (_directory, _stem_lower), g in by_stem.items():
        dt = g.get('dt')
        records.append(PhotoRecord(
            identity=_make_identity(g['stem_display'], dt),
            stem=g['stem_display'],
            jpg_path=g.get('jpg'),
            raw_path=g.get('raw'),
            capture_dt=dt,
            date_uncertain=g.get('uncertain', dt is None),
        ))

    records.sort(key=lambda r: (r.capture_dt or datetime.min, r.stem))
    return records


def group_by_date(records):
    """{date: [PhotoRecord, ...]} sorted by date, each list sorted by
    capture time ascending. Photos with no resolvable date (no EXIF and no
    mtime, essentially never in practice) land under the None key."""
    groups = {}
    for r in records:
        groups.setdefault(r.date, []).append(r)
    for recs in groups.values():
        recs.sort(key=lambda r: r.capture_dt or datetime.min)
    return dict(sorted(groups.items(), key=lambda kv: (kv[0] is None, kv[0])))
