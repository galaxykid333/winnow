# Winnow — build spec

A desktop app for culling and tagging bird photographs, for a single user
(a birder and computational scientist, Python-primary, macOS, OM System OM-1).

**The name.** To winnow is to separate grain from chaff — the culling operation
itself. It's also the drumming display flight of a snipe, made by air through
the outer tail feathers. Both readings are intended.

Hand this file plus `winnow-prototype.html` to Claude Code. The
prototype is the validated interaction design — the real app should reproduce
its behaviour, not reinvent it.

---

## 1. Why this exists

Two problems, in priority order:

1. **The archive isn't searchable.** Years of photos live in `date-location`
   folders with no species information. The question "show me all my dunnocks"
   has no answer. This is the primary motivation.
2. **Going through photos is unpleasant.** Existing tools are either overwhelming
   (darktable) or subscription-based and not bird-aware (Lightroom). Culling
   should feel calm and finish.

Success is measured by: can a session be tagged in one enjoyable pass, and can
the archive be queried afterwards in one line.

## 2. Scope of this build

**In scope:** the complete manual workflow — ingest, cull, tag, write XMP,
move files, query.

**Deliberately out of scope:** automatic bird detection and species ID. That
comes later and must not shape the design now. See §9 for where it plugs in.

The user is the classifier for v1. This is intentional — it de-risks the
workflow before adding an unproven model.

## 3. Design principles (do not violate)

These came out of the user's reaction to darktable's lighttable, which she found
overwhelming. They are hard constraints, not preferences.

- **One screen, one job.** No permanently visible side panels. The cull screen
  shows a photo, three buttons, and a tag field. Nothing else.
- **Settings live behind a settings screen**, never on the main canvas.
- **Keyboard-first, single keys, no chords** — but every keyboard action must
  also have a visible clickable control. Some days she wants the mouse. The
  mouse-only path must be complete, including finishing a session.
- **Never present a blank state.** Species carries over from the previous photo.
- **Nothing is destroyed.** Discarded photos are never deleted, only left behind
  or moved to a separate folder. Undo always available.
- Adding a feature must not add a control to the cull screen. If it would, it
  belongs on another screen or doesn't ship.

## 4. Stack

- **pywebview** — native macOS window wrapping the HTML/CSS/JS front-end.
  Chosen so the eventual ML lives in the same Python process, and so the app
  can be packaged as a double-clickable `.app` (startup friction matters).
- Front-end: the prototype's vanilla HTML/CSS/JS. No build step. Do not
  introduce React unless there's a concrete reason.
- `exiftool` via subprocess for metadata. More reliable than Python XMP
  libraries. Document it as a dependency (`brew install exiftool`).
- Python API exposed to JS via pywebview's `js_api` bridge.

## 5. File handling

The camera writes **RAW + JPEG pairs** to the SD card (`P2250011.ORF` and
`P2250011.JPG`). This is the user's existing habit — do not require changing it.

**Pairing:** match on filename stem, case-insensitive. A JPEG with no ORF is
still valid (treat the JPEG as the master). An ORF with no JPEG should be
flagged, not silently skipped — offer to extract the embedded preview via
`exiftool -b -PreviewImage`.

**Input folder:** user picks it (SD card or anywhere). Read-only. Never write
to or delete from the input folder. Sessions are scoped to selected capture
dates rather than the whole folder — see `SESSION-FLOW.md`.

**Output folder:** user picks it. On finishing a session:

- For each **kept** photo: copy or move the ORF (user's choice, default copy —
  moving off an SD card before verifying is risky) into the output folder.
- Write an XMP sidecar next to the copied ORF.
- The JPEG is a viewing proxy. Default to not copying it; make it an option.
- **Discarded** photos: do nothing at all by default. They stay on the card.
  Optionally copy to an output subfolder. Never delete.

Both folder choices should be remembered between sessions.

**Performance:** JPEGs from an OM-1 are ~10MB. Do not load full-size images into
the webview. Generate downscaled previews (long edge ~2000px) into a cache dir
on ingest, serve those, and show a progress indicator while it runs. Cache is
disposable and regenerable.

## 6. Screens

### Start
Superseded — see `SESSION-FLOW.md`. The flow is input folder → calendar →
destination → cull, so that one outing is processed at a time and sessions
can be paused and resumed.

### Cull (the core screen)
Photo fills the space. Below it, three buttons: **Keep** / **Keep & mark great**
/ **Discard**. Below that, the tag field, visible only after a keep. Above the
photo, a thumbnail strip that expands into a grid — see `SESSION-FLOW.md` §3–4.

Keeping opens the tag field pre-filled with the previous species. Discarding
skips tagging and advances immediately.

**Keyboard map** (as validated in the prototype):

| Key | View mode | Tag mode |
|---|---|---|
| `↓` / `↑` | next / previous photo | same |
| `←` / `→` | move cursor across the three buttons | text caret |
| `enter` | confirm the button under the cursor | add top suggestion; if field empty, next photo |
| `space` | keep | — |
| `g` | keep & mark great | — |
| `x` | discard | — |
| `1`–`5` | — | add that suggestion |
| `backspace` | — | on empty field, remove last tag (notes before species) |
| `esc` | — | next photo, leave untagged |
| `u` | undo | — |
| `f` | finish session | — |

The verdict keys must call `preventDefault()` — otherwise the keystroke lands in
the tag field that just took focus. This was a real bug in an earlier version.

The button cursor persists between photos, so runs of the same verdict are one
key each.

### Review / output
Table of kept photos with **thumbnails**, filename, species, notes, and the great
marker. Search box plus clickable filter chips for every tag used in the session.
This is where the user confirms the session did what she expected before writing
anything to disk.

## 7. Tag schema

XMP hierarchical keywords, because exiftool, Lightroom, and digiKam all read them.

```
Bird|Dunnock          species — repeatable, a photo may have several
Mammal|Roe deer        \
Amphibian|Common frog   > parallel branches, same schema as Bird|, see below
Reptile|Adder          /
Also|Blue tit          secondary or background birds
Note|Nesting           behaviour and context notes — repeatable
Site|Spurn             set once per session
Status|Confirmed       Confirmed by the user, or Unconfirmed from a model
```

- **Species must be multi-valued from day one.** A photo can contain more than
  one species. Retrofitting this later is painful.
- **"Great" is written as `xmp:Rating` = 5**, not a keyword — every other tool
  reads that field, so marked photos light up in Finder, Lightroom, and digiKam
  with no translation. 1–4 stay unused and available.
- Date needs no tag. It's already in EXIF; season is derived at query time.

**Subject branches beyond birds.** A roe deer can't live under `Bird|`, so each
kind of subject gets its own parallel branch — `Mammal|`, `Amphibian|`,
`Reptile|`, and whatever gets added later (butterflies, dragonflies, ...). In
the UI these are not a separate feature: a mammal chip is a species chip, same
green as a bird, because the distinction that matters when culling is subject
vs. note, not which taxon the subject belongs to. Only the XMP branch differs,
and that's resolved at write time from the vocabulary files (a photo's tag
list only ever stores the common name, e.g. "Roe deer" — see
`vocab.branch_for_name` in `output.py`). A name not found in any vocabulary
file falls back to `Bird|`, so tags written before this existed stay valid
with no migration.

**Vocabulary is data-driven, not hardcoded.** Every `*-tags.json` file in the
repo root defines one branch:

```json
{
  "Mammal": [["Roe deer", "Capreolus capreolus"], ["Badger", "Meles meles"]],
  "_aliases": {"European rabbit": "Rabbit", "Reeves's muntjac": "Muntjac"}
}
```

`bird-tags.json` and `wildlife-tags.json` (mammals, amphibians, reptiles) ship
with the app; adding a new branch — butterflies, dragonflies — means dropping
in another file with the same shape, no code change. `_aliases` maps a typed
phrase to the canonical common name it should resolve to, so `european
rabbit` finds Rabbit and `muntjac` finds Muntjac even though neither is the
literal listed name. The front-end loads and merges all of them into one
searchable index at startup (`vocab.py` on the Python side); typing `ro`
surfaces Robin and Roe deer together, and the suggestion list shows which
branch each hit belongs to in the small label next to it.

**Notes vocabulary** goes through the same input field as species — one field,
two vocabularies, distinguished by chip colour (species green, notes blue). Seed
list with aliases so `baby` finds Juvenile and `bif` finds In flight:

> Multiple birds · Juvenile · Nesting · In flight · Feeding · Displaying ·
> Perched · Swimming · Pair · Flock · Calling · Ringed bird · Habitat · Portrait

Unrecognised input offers itself as a new note on the last suggestion and joins
the list. Persist user-created notes across sessions in a config file.

**Species list:** `bird-tags.json` carries ~190 common British species with
scientific names (the full BOU British list is a future replacement for that
one file, not a code change). Match on word-start across all words, so `godw`
finds both godwits — the same matching applies uniformly across every
branch, not just birds.

## 8. Query layer

XMP in the files is the durable truth. Maintain a **SQLite index derived from it**
— disposable, rebuildable by rescanning, but it's what makes queries instant and
date arithmetic bearable.

Ship a small CLI:

```
winnow find --species dunnock
winnow find --species robin --month 3-5 --rated
winnow find --site Spurn --species "bar-tailed godwit" --since 2024
winnow reindex /path/to/archive
```

`reindex` must work on the existing backlog of `date-location` folders, not just
photos processed by this app.

## 9. Where the ML will plug in (build the socket, not the model)

Later, a Python function will take an image path and return:

```python
{"boxes": [{"bbox": [x, y, w, h],
            "species": [("Curlew", 0.91), ("Whimbrel", 0.06), ...],
            "sharpness": 0.72}]}
```

Planned: YOLO for bird detection, BioCLIP 2 for species (text embeddings for the
candidate species list cached once, so per-image cost is the vision encoder plus
a dot product). Later still, eBird regional frequency data to constrain
candidates by place and week — that's what kills most misidentifications.

For now, **stub this function** so it returns nothing. The tag field already has
a suggestion row; the model will populate it, and the layout will not move. Keep
`Status|Unconfirmed` in the schema so model-supplied tags are distinguishable
from confirmed ones.

Do not build any of this in v1.

## 10. Build order

1. pywebview shell loading the prototype front-end unchanged.
2. Ingest: scan input folder, read EXIF dates only, pair RAW+JPEG, build index.
3. Calendar and destination screens (`SESSION-FLOW.md` §2).
4. Preview and thumbnail caches for the selected dates, generated lazily.
5. Wire the cull/tag UI to real files via the JS bridge.
6. Thumbnail strip and grid view (`SESSION-FLOW.md` §3–5).
7. Session persistence — an interrupted session must resume exactly where it
   stopped. Not optional; sessions will be interrupted.
8. Output: copy files, write XMP via exiftool, verify by reading back.
9. SQLite index + `winnow find` CLI.
10. Package as a `.app`.

## 11. Open questions to resolve while building

- Does the carried-over species help or cause mis-tags? If it bites, change it
  from a pre-filled value to a suggestion requiring one key to accept.
- Does the persistent button cursor cause accidental discards? If so, reset it
  to Keep on each photo.
- Does "Discard" read as too final and cause hesitation on borderline photos?
  Renaming is cheap; the hesitation is not.
- Do user-created notes accumulate near-duplicates (`Nesting` / `On nest`)? If
  so, offer close matches before offering to create a new one.
