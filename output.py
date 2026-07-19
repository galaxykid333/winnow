"""Writes a session to disk: copies (or moves) each kept photo's master
file into the destination folder and writes an XMP sidecar next to it —
SPEC.md §5, build order step 8.

Never destructive on failure. Every write lands at a temp name first and is
only renamed into place after a size check (file copies) or a read-back
check (XMP sidecars) confirms it's good — so a cancelled or crashed write
never leaves a half-written sidecar, and never leaves a partially-copied
file that a later skip-on-size-match resume would mistake for complete.

Resumable per SESSION-FLOW.md §6.1: a master file already present at the
destination with a matching size is left alone. XMP sidecars are always
regenerated from current tags — cheap to rewrite, and the whole reason the
review screen lets you go back and fix tags is that a stale sidecar
shouldn't survive that.
"""

import json
import os
import shutil
import subprocess

import exiftool_path

XMP_TIMEOUT = 30


def _copy_with_resume(src, dest_dir):
    """Copy src into dest_dir, skipping if a same-size file already exists
    there (resume) and replacing if the size differs (prior failed copy).
    Returns ('skipped'|'copied', dest_path) or raises on real failure."""
    dest_path = os.path.join(dest_dir, os.path.basename(src))
    src_size = os.path.getsize(src)

    if os.path.exists(dest_path):
        if os.path.getsize(dest_path) == src_size:
            return 'skipped', dest_path
        # size differs: a previous crashed/interrupted copy — fall through
        # and overwrite via the same temp-then-rename path as a fresh copy

    tmp_path = f'{dest_path}.tmp-{os.getpid()}'
    try:
        shutil.copyfile(src, tmp_path)
        if os.path.getsize(tmp_path) != src_size:
            raise IOError(
                f'copied size {os.path.getsize(tmp_path)} does not match source size {src_size}'
            )
        os.replace(tmp_path, dest_path)  # atomic — never a half-written file at dest_path
    except Exception:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise
    return 'copied', dest_path


def _xmp_tags(record):
    tags = []
    for s in record['sp']:
        tags.append(f'Bird|{s}')
    for n in record['nt']:
        tags.append(f'Note|{n}')
    if record.get('location'):
        tags.append(f'Site|{record["location"]}')
    tags.append('Status|Confirmed')  # v1 is manual-only — see SPEC.md §9
    return tags


def _write_xmp_sidecar(record, dest_dir):
    """Write <stem>.xmp in dest_dir from record's current tags, verifying
    by reading the tags back before the temp file is renamed into place.
    Returns (True, None) or (False, reason)."""
    exiftool_bin, _version = exiftool_path.resolve()
    if not exiftool_bin:
        return False, 'exiftool not found (see Settings)'

    dest_path = os.path.join(dest_dir, f'{record["stem"]}.xmp')
    # Must still end in .xmp: exiftool's -o infers the output format from
    # the given filename's extension, so a suffix like ".xmp.tmp-1234"
    # makes it try to create a "TMP-1234" file and fail. Confirmed directly.
    tmp_path = os.path.join(dest_dir, f'{record["stem"]}.tmp-{os.getpid()}.xmp')
    if os.path.exists(tmp_path):
        os.remove(tmp_path)

    tags = _xmp_tags(record)
    cmd = [exiftool_bin]
    for t in tags:
        cmd.append(f'-HierarchicalSubject+={t}')
    cmd += ['-Rating=5' if record['great'] else '-Rating=0', '-o', tmp_path]
    # Deliberately no source file argument: we're not copying anything FROM
    # the raw file, only setting new tags, and requiring the source to be a
    # parseable image (exiftool errors on an unrecognized/corrupt one) would
    # make sidecar writing depend on the raw file for no reason.

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=XMP_TIMEOUT)
    if result.returncode != 0 or not os.path.exists(tmp_path):
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        return False, f'exiftool exit {result.returncode}: {result.stderr.strip()}'

    verify = subprocess.run(
        [exiftool_bin, '-j', '-HierarchicalSubject', '-Rating', tmp_path],
        capture_output=True, text=True, timeout=XMP_TIMEOUT,
    )
    try:
        read_back = json.loads(verify.stdout)[0]
    except (json.JSONDecodeError, IndexError, KeyError):
        os.remove(tmp_path)
        return False, f"couldn't read tags back from the sidecar we just wrote: {verify.stderr.strip()}"

    got = set(read_back.get('HierarchicalSubject', []) or [])
    if not set(tags).issubset(got):
        os.remove(tmp_path)
        missing = set(tags) - got
        return False, f'read-back is missing tags we just wrote: {sorted(missing)}'

    os.replace(tmp_path, dest_path)  # atomic — never a half-written sidecar at dest_path
    return True, None


def read_sidecar(xmp_path):
    """Read an actually-written sidecar back via exiftool — used by the
    review screen's 'written' state to show real content, never a
    hypothetical preview. Returns {'ok': True, 'hierarchical_subject': [...],
    'rating': int} or {'ok': False, 'reason': str}."""
    exiftool_bin, _version = exiftool_path.resolve()
    if not exiftool_bin:
        return {'ok': False, 'reason': 'exiftool not found (see Settings)'}
    if not os.path.exists(xmp_path):
        return {'ok': False, 'reason': 'file not found'}
    result = subprocess.run(
        [exiftool_bin, '-j', '-HierarchicalSubject', '-Rating', xmp_path],
        capture_output=True, text=True, timeout=XMP_TIMEOUT,
    )
    try:
        data = json.loads(result.stdout)[0]
    except (json.JSONDecodeError, IndexError):
        return {'ok': False, 'reason': result.stderr.strip() or 'could not read tags'}
    return {
        'ok': True,
        'hierarchical_subject': data.get('HierarchicalSubject', []) or [],
        'rating': data.get('Rating', 0),
    }


def write_session(dest_dir, records, options, progress_cb=None, cancel_check=None):
    """records: list of dicts with identity, stem, raw_path, jpg_path, sp,
    nt, great, location — one per kept photo, in the order to process them.
    options: {'raw_handling': 'copy'|'move', 'copy_jpegs': bool}.
    progress_cb(done, total, stem) is called before each file starts.
    cancel_check() returning True stops before starting the next file.

    Returns {'results': [...], 'cancelled': bool} — never raises for a
    single file's failure; every photo gets its own success/failure record
    rather than aborting the whole run.
    """
    os.makedirs(dest_dir, exist_ok=True)
    results = []
    total = len(records)

    for done, record in enumerate(records):
        if cancel_check and cancel_check():
            return {'results': results, 'cancelled': True}

        if progress_cb:
            progress_cb(done, total, record['stem'])

        entry = {'identity': record['identity'], 'stem': record['stem'], 'errors': []}
        master = record.get('raw_path') or record.get('jpg_path')

        if not master:
            entry['errors'].append('no raw or jpeg file found for this photo')
            entry['master_status'] = 'failed'
            results.append(entry)
            continue

        try:
            status, master_dest = _copy_with_resume(master, dest_dir)
            entry['master_status'] = status
            entry['master_path'] = master_dest
            if options.get('raw_handling') == 'move' and record.get('raw_path'):
                # Only ever delete the source after a verified copy exists —
                # moving before verifying is the exact risk SPEC.md §5 and
                # CLAUDE.md both call out.
                os.remove(master)
                entry['master_status'] = 'moved'
        except Exception as exc:
            entry['master_status'] = 'failed'
            entry['errors'].append(f'copying {os.path.basename(master)}: {exc}')

        if options.get('copy_jpegs') and record.get('jpg_path') and record.get('raw_path'):
            try:
                jpg_status, jpg_dest = _copy_with_resume(record['jpg_path'], dest_dir)
                entry['jpeg_status'] = jpg_status
                entry['jpeg_path'] = jpg_dest
            except Exception as exc:
                entry['jpeg_status'] = 'failed'
                entry['errors'].append(f'copying jpeg {os.path.basename(record["jpg_path"])}: {exc}')

        ok, reason = _write_xmp_sidecar(record, dest_dir)
        entry['xmp_written'] = ok
        if not ok:
            entry['errors'].append(f'xmp sidecar: {reason}')
        else:
            entry['xmp_path'] = os.path.join(dest_dir, f'{record["stem"]}.xmp')

        results.append(entry)

    if progress_cb:
        progress_cb(total, total, None)
    return {'results': results, 'cancelled': False}
