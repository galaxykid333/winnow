import json
import os
import subprocess
import threading
import traceback

import webview

import exiftool_path
import output
import state
from cache import CacheManager
from ingest import group_by_date, scan_input_folder

CONFIG_PATH = os.path.expanduser('~/Library/Application Support/Winnow/config.json')


class Api:
    def __init__(self):
        self._records_by_date = {}      # date -> [PhotoRecord], from the last completed scan
        self._records_by_identity = {}  # identity -> PhotoRecord, same data, keyed for cache lookups
        self._cache = None              # created lazily, once webview.windows[0] exists
        self._write_running = False
        self._write_cancel = threading.Event()

    def get_exiftool_status(self):
        """For the settings screen — double-clicking the .app gives it a
        minimal PATH that often can't find a Homebrew-installed exiftool,
        so this is the only way to see what actually resolved without
        opening Console.app."""
        path, version = exiftool_path.resolve()
        return {'found': bool(path), 'path': path, 'version': version}

    def pick_folder(self, title):
        result = webview.windows[0].create_file_dialog(webview.FileDialog.FOLDER)
        if result:
            return result[0]
        return None

    def start_scan(self, folder):
        """Kick off a background ingest scan and return immediately. Progress
        and the result are pushed to the front-end via evaluate_js, because a
        scan of a full SD card is far too slow for a normal js_api call."""
        threading.Thread(target=self._run_scan, args=(folder,), daemon=True).start()
        return True

    def _run_scan(self, folder):
        window = webview.windows[0]

        def on_progress(done, total):
            window.evaluate_js(f'onScanProgress({done},{total})')

        try:
            records = scan_input_folder(folder, progress_cb=on_progress)
        except Exception as exc:
            traceback.print_exc()  # otherwise this is invisible when launched by double-click
            window.evaluate_js(f'onScanError({json.dumps(str(exc))})')
            return

        self._records_by_date = group_by_date(records)
        self._records_by_identity = {r.identity: r for r in records}
        window.evaluate_js(f'onScanComplete({json.dumps(self._date_summary())})')

    def _date_summary(self):
        reviewed = state.all_reviewed_identities()
        return [
            {
                'date': d.isoformat() if d else None,
                'count': len(recs),
                'uncertain': any(r.date_uncertain for r in recs),
                'reviewed': sum(1 for r in recs if r.identity in reviewed),
            }
            for d, recs in self._records_by_date.items()
        ]

    def photos_for_dates(self, dates):
        """dates: list of 'YYYY-MM-DD' strings. Returns PhotoRecords for
        those dates, capture-time ascending, as plain dicts."""
        wanted = set(dates)
        out = []
        # self._records_by_date is already date-ordered, and each date's list
        # is already capture-time ordered, so concatenating preserves order.
        for d, recs in self._records_by_date.items():
            if d and d.isoformat() in wanted:
                out.extend(recs)
        return [r.to_dict() for r in out]

    def open_session(self, dest_path, parent_folder, location, dates):
        """Create or resume the session for this destination folder. Returns
        the review state already recorded for it — {} for a brand-new one."""
        return state.open_session(dest_path, parent_folder, location, dates)

    def save_verdict(self, dest_path, identity, verdict, great, sp, nt):
        """Write through a single photo's verdict/tags immediately, so a
        crash mid-session loses at most the one in-flight action."""
        state.save_verdict(dest_path, identity, verdict, great, sp, nt)
        return True

    def start_write(self, dest_path):
        """Kick off the real write step (output.py) in a background thread
        and return immediately — mirrors start_scan. Returns False without
        doing anything if a write is already running, guarding a double
        click on 'Write' or a stray click while one is in flight."""
        if self._write_running:
            return False
        self._write_running = True
        self._write_cancel.clear()
        threading.Thread(target=self._run_write, args=(dest_path,), daemon=True).start()
        return True

    def cancel_write(self):
        if self._write_running:
            self._write_cancel.set()
        return True

    def _run_write(self, dest_path):
        window = webview.windows[0]
        try:
            records = self._build_write_records(dest_path)
            cfg = self.load_config()
            options = {
                'raw_handling': cfg.get('raw_handling', 'copy'),
                'copy_jpegs': cfg.get('copy_jpegs', False),
            }

            def on_progress(done, total, stem):
                window.evaluate_js(f'onWriteProgress({done},{total},{json.dumps(stem)})')

            result = output.write_session(
                dest_path, records, options,
                progress_cb=on_progress,
                cancel_check=self._write_cancel.is_set,
            )
            window.evaluate_js(f'onWriteComplete({json.dumps(result)})')
        except Exception as exc:
            traceback.print_exc()  # otherwise this is invisible when launched by double-click
            window.evaluate_js(f'onWriteError({json.dumps(str(exc))})')
        finally:
            self._write_running = False

    def _build_write_records(self, dest_path):
        """Reconstruct the write list from server-side state, never from
        the JS bridge: self._records_by_identity (file paths, from the last
        scan) cross-referenced with the persisted review state (current
        tags, always freshly read so a revised verdict/tag after 'back to
        culling' is picked up), filtered to verdict=='keep', plus the
        session's location for the Site| tag."""
        review = state.load_review_state(dest_path)
        location = state.session_location(dest_path)
        kept = {identity: r for identity, r in review.items() if r['verdict'] == 'keep'}

        records = []
        seen = set()
        # self._records_by_identity is insertion-ordered = capture-time
        # order (scan_input_folder returns records sorted that way), so
        # this keeps write order matching what the review table showed.
        for identity, pr in self._records_by_identity.items():
            r = kept.get(identity)
            if not r:
                continue
            seen.add(identity)
            records.append({
                'identity': identity, 'stem': pr.stem,
                'raw_path': pr.raw_path, 'jpg_path': pr.jpg_path,
                'sp': r['sp'], 'nt': r['nt'], 'great': r['great'],
                'location': location,
            })

        # A kept identity absent from the current in-memory scan (e.g. the
        # input folder was rescanned since) would otherwise be silently
        # dropped from the write. Surface it as a per-file failure instead —
        # output.write_session already reports a clear reason for a record
        # with no raw_path/jpg_path.
        for identity, r in kept.items():
            if identity in seen:
                continue
            records.append({
                'identity': identity, 'stem': identity,
                'raw_path': None, 'jpg_path': None,
                'sp': r['sp'], 'nt': r['nt'], 'great': r['great'],
                'location': location,
            })
        return records

    def read_sidecar(self, xmp_path):
        """Read an actually-written sidecar back via exiftool — used by the
        review screen's 'written' state to show real content, never a
        hypothetical preview."""
        return output.read_sidecar(xmp_path)

    def reveal_in_finder(self, path):
        subprocess.run(['open', '-R', path])
        return True

    def _ensure_cache(self):
        if self._cache is None:
            window = webview.windows[0]

            def on_ready(identity, kind, path):
                # path is None on failure (see cache.py) — passed through as
                # JS null so the front-end can show a failed state instead
                # of leaving the thumbnail blank forever.
                url = ('file://' + path) if path else None
                window.evaluate_js(
                    f'onCacheReady({json.dumps(identity)},{json.dumps(kind)},{json.dumps(url)})'
                )

            self._cache = CacheManager(on_ready=on_ready)
        return self._cache

    def request_image(self, identity, kind, priority=0):
        """Return a file:// URL for the cached thumbnail/preview if it
        already exists. Otherwise queue generation (see cache.py) and
        return None — the front-end learns it's ready via onCacheReady."""
        record = self._records_by_identity.get(identity)
        if not record:
            return None
        path = self._ensure_cache().request(record.to_dict(), kind, priority=priority)
        return ('file://' + path) if path else None

    def load_config(self):
        if os.path.exists(CONFIG_PATH):
            try:
                with open(CONFIG_PATH) as f:
                    data = json.load(f)
                return {
                    'input_folder': data.get('input_folder', ''),
                    'parent_folder': data.get('parent_folder', ''),
                    'locations': data.get('locations', []),
                    'raw_handling': data.get('raw_handling', 'copy'),
                    'copy_jpegs': data.get('copy_jpegs', False),
                }
            except Exception:
                pass
        return {
            'input_folder': '', 'parent_folder': '', 'locations': [],
            'raw_handling': 'copy', 'copy_jpegs': False,
        }

    def save_config(self, data):
        os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
        existing = {}
        if os.path.exists(CONFIG_PATH):
            try:
                with open(CONFIG_PATH) as f:
                    existing = json.load(f)
            except Exception:
                pass
        existing.update(data)
        with open(CONFIG_PATH, 'w') as f:
            json.dump(existing, f, indent=2)
        return True

    def folder_exists(self, parent, name):
        return bool(parent) and bool(name) and os.path.isdir(os.path.join(parent, name))

    def add_location(self, name):
        """Record a used location, most-recent first, deduped case-insensitively."""
        os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
        existing = {}
        if os.path.exists(CONFIG_PATH):
            try:
                with open(CONFIG_PATH) as f:
                    existing = json.load(f)
            except Exception:
                pass
        locations = [l for l in existing.get('locations', []) if l.lower() != name.lower()]
        locations.insert(0, name)
        existing['locations'] = locations[:50]
        with open(CONFIG_PATH, 'w') as f:
            json.dump(existing, f, indent=2)
        return existing['locations']
