"""Session and review-state persistence. An interrupted session must resume
exactly where it stopped (docs/SPEC.md build step 7) — every verdict/tag change
here writes through immediately, so a crash loses at most the one in-flight
action, never the whole session.

Lives in ~/Library/Application Support/Winnow/, not the input folder (which
is read-only) and not the destination folder (which may not exist yet, or
may get renamed) — see docs/SESSION-FLOW.md §7.

Keyed by (dest_path, photo identity). `dest_path` is the resume key: opening
the same destination folder again is what "resuming" means, per
docs/SESSION-FLOW.md §2.3. Photo identity is ingest.py's stem+capture-second id,
stable across rescans — see docs/SESSION-FLOW.md §7.
"""

import json
import os
import sqlite3
import threading
from datetime import datetime, timezone

DB_PATH = os.path.expanduser('~/Library/Application Support/Winnow/winnow.db')

_lock = threading.Lock()  # serializes all DB access; call volume is tiny, simplicity wins


def _connect():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('''CREATE TABLE IF NOT EXISTS sessions(
        dest_path TEXT PRIMARY KEY,
        parent_folder TEXT,
        location TEXT,
        dates TEXT,
        created_at TEXT,
        updated_at TEXT
    )''')
    conn.execute('''CREATE TABLE IF NOT EXISTS review_state(
        dest_path TEXT NOT NULL,
        identity TEXT NOT NULL,
        verdict TEXT,
        great INTEGER NOT NULL DEFAULT 0,
        species TEXT NOT NULL DEFAULT '[]',
        notes TEXT NOT NULL DEFAULT '[]',
        PRIMARY KEY (dest_path, identity)
    )''')
    return conn


def _now():
    return datetime.now(timezone.utc).isoformat()


def _rows_to_review_state(rows):
    return {
        identity: {
            'verdict': verdict,
            'great': bool(great),
            'sp': json.loads(species),
            'nt': json.loads(notes),
        }
        for identity, verdict, great, species, notes in rows
    }


def open_session(dest_path, parent_folder, location, dates):
    """Create the session row if this destination is new, otherwise just
    touch it. Returns the review state already recorded for it, as
    {identity: {verdict, great, sp, nt}} — empty for a brand-new session."""
    now = _now()
    with _lock, _connect() as conn:
        exists = conn.execute(
            'SELECT 1 FROM sessions WHERE dest_path=?', (dest_path,)
        ).fetchone()
        if exists:
            conn.execute('UPDATE sessions SET updated_at=? WHERE dest_path=?', (now, dest_path))
        else:
            conn.execute(
                'INSERT INTO sessions(dest_path,parent_folder,location,dates,created_at,updated_at) '
                'VALUES (?,?,?,?,?,?)',
                (dest_path, parent_folder, location, json.dumps(dates), now, now),
            )
        rows = conn.execute(
            'SELECT identity, verdict, great, species, notes FROM review_state WHERE dest_path=?',
            (dest_path,),
        ).fetchall()
        conn.commit()

    return _rows_to_review_state(rows)


def load_review_state(dest_path):
    """Like the dict returned by open_session, without touching the
    sessions table — used by the write step, which just needs current
    tags, not to re-create or re-touch the session."""
    with _lock, _connect() as conn:
        rows = conn.execute(
            'SELECT identity, verdict, great, species, notes FROM review_state WHERE dest_path=?',
            (dest_path,),
        ).fetchall()
    return _rows_to_review_state(rows)


def session_location(dest_path):
    """The location string recorded for this session (Site| tag on write)."""
    with _lock, _connect() as conn:
        row = conn.execute(
            'SELECT location FROM sessions WHERE dest_path=?', (dest_path,)
        ).fetchone()
    return row[0] if row else ''


def save_verdict(dest_path, identity, verdict, great, sp, nt):
    """Write through a single photo's review state. `verdict=None` (as
    undo produces) correctly clears it back to unreviewed."""
    with _lock, _connect() as conn:
        conn.execute(
            '''INSERT INTO review_state(dest_path,identity,verdict,great,species,notes)
               VALUES (?,?,?,?,?,?)
               ON CONFLICT(dest_path,identity) DO UPDATE SET
                 verdict=excluded.verdict, great=excluded.great,
                 species=excluded.species, notes=excluded.notes''',
            (dest_path, identity, verdict, int(bool(great)), json.dumps(sp), json.dumps(nt)),
        )
        conn.commit()


def all_reviewed_identities():
    """Every photo identity with a verdict, across all sessions — used to
    paint the calendar's reviewed-fraction ring (docs/SESSION-FLOW.md §2.2).
    Deliberately not scoped to one session: whether a given photo has been
    looked at is a global fact about that photo, not the folder it was
    reviewed under."""
    with _lock, _connect() as conn:
        rows = conn.execute(
            'SELECT identity FROM review_state WHERE verdict IS NOT NULL'
        ).fetchall()
        return {r[0] for r in rows}
