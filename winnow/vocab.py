"""Subject tag vocabulary (birds, mammals, amphibians, reptiles, ...) is
data-driven: any `*-tags.json` file in data/ defines one or more parallel
XMP branches. Adding a new branch (e.g. butterflies) means dropping in a
new JSON file with the same shape -- no code change here. See
docs/SPEC.md §7.

Schema per file:
    {
      "Branch": [["Common name", "Scientific name"], ...],
      "_aliases": {"typed phrase": "canonical common name"}
    }

A photo's species chips only ever store the common name (e.g. "Roe deer"),
never the branch -- branch_for_name() below is how the write step (output.py)
recovers which XMP branch a name belongs to when it writes the sidecar.
"""

import glob
import json
import os
from pathlib import Path

# Resolved from this module's own location, not the working directory --
# the app is routinely launched by double-clicking a .app bundle, where cwd
# is unpredictable (Finder, launchd, or whatever last called `open`), not
# necessarily the repo root.
DATA_DIR = Path(__file__).resolve().parent.parent / 'data'

_cache = None


def load_species_vocabulary(force_reload=False):
    """Merge every *-tags.json in data/ into one vocabulary:
    {'branches': {branch: [[common, sci], ...], ...}, 'aliases': {alias: canonical}}.
    Cached after the first call -- these files don't change during a run."""
    global _cache
    if _cache is not None and not force_reload:
        return _cache

    branches = {}
    aliases = {}
    for path in sorted(glob.glob(os.path.join(DATA_DIR, '*-tags.json'))):
        with open(path) as f:
            data = json.load(f)
        for key, entries in data.items():
            if key.startswith('_'):
                continue
            branches.setdefault(key, []).extend(entries)
        for alias, canonical in data.get('_aliases', {}).items():
            aliases[alias] = canonical

    _cache = {'branches': branches, 'aliases': aliases}
    return _cache


def branch_for_name(name):
    """Which subject branch a common name belongs to, for the XMP tag
    prefix (Bird|/Mammal|/...). Falls back to 'Bird' for a name not found
    in any vocabulary file -- every tag recorded before wildlife subjects
    existed was bird-only, so unrecognized legacy names still write
    correctly without a migration."""
    vocab = load_species_vocabulary()
    for branch, entries in vocab['branches'].items():
        if any(common == name for common, _sci in entries):
            return branch
    return 'Bird'
