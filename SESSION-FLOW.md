# Winnow — session flow and navigation

Implementation brief. Supersedes the start-of-session and cull-screen
navigation described in `SPEC.md` §5–6. Everything in `CLAUDE.md` still applies.

Plan before writing code.

---

## 1. The problem

The input folder is an SD card holding thousands of photos across several
outings. Work happens one outing at a time, and a single day may be too much
for one sitting. So: pick a date, process that day's photos, stop whenever,
resume later exactly where you stopped.

## 2. Flow

```
input folder → calendar → destination → cull
```

### 2.1 Input folder

User picks it. Scan and index by capture date. Show a progress indicator —
this may be thousands of files.

Read **only the EXIF date** during this scan. Do not generate previews or
thumbnails for the whole card; those come after a date is chosen. Use a single
batched `exiftool` call over the directory, not one call per file.

### 2.2 Calendar

Month calendar. Only days that contain photos are active; empty days are
visibly inert. User can move between months.

Each active day shows:
- the number of photos taken that day
- a visual indication of how much of that day has already been reviewed
  (partial fill, ring, or similar — reviewed vs total)

Selection supports both a contiguous shift-range and non-contiguous picks.

### 2.3 Destination

After date selection:

- **Parent folder** — remembered from the last session, changeable.
- **Location** — typed, with autocomplete from previously used locations.
- **Folder name** — generated, shown before committing, and editable:
  - one day: `2026-07-19 Spurn`
  - range: `2026-07-19 - 2026-07-21 Spurn`
- **If the folder already exists**, treat it as resuming. Do not error, do not
  overwrite.

### 2.4 Cull

The prototype's cull screen, scoped to the selected date(s), plus the thumbnail
strip described in §3. Progress bar showing position in the session.

## 3. Thumbnail strip

A horizontal filmstrip at the **top** of the cull screen, above the photo.
Standard layout, like Topaz Photo AI's, but top rather than bottom.

**This replaces the coloured dot strip in the prototype. Remove that.**

- Photos ordered by **EXIF capture time, ascending**. Not filename.
- Shows every photo in the current session.
- Current photo clearly marked; strip auto-scrolls to keep it in view.
- Click a thumbnail to jump to it.
- **Must not steal keyboard focus.** After clicking a thumbnail, pressing
  `space` must register as "keep" immediately.
- One key collapses and expands it.

This is the only persistent chrome permitted on the cull screen. It earns that
because it reports state rather than offering controls. The photo must remain
the dominant element when the tag field is open — verify at 13" laptop height,
not just full screen.

## 4. Grid view

The strip expands into a full grid filling the window — Finder's icon view.
Same photos, same order.

- One key toggles strip ↔ grid. Proposed: `tab`. It must not move focus; if
  that proves awkward, propose an alternative rather than breaking the
  existing keyboard map.
- The current photo stays current across the toggle, and the grid opens
  scrolled to it.
- Click a thumbnail to jump to it and return to the cull screen.
- Adjustable thumbnail size, Finder-style (slider or `+`/`-`).
- Arrow keys move a selection cursor; `enter` jumps to the selected photo and
  returns to culling.
- Show a quiet session summary: reviewed, kept, discarded, remaining.

### 4.1 Bulk discard — decided, discard only

The grid may apply verdicts directly, but **only discard**.

- Select a range (shift-click, shift-arrows) and discard the selection in one
  action.
- **No bulk keep, and no bulk tagging.** Keeping always goes through the
  one-at-a-time loop, because keeping is what triggers tagging and tagging is
  the entire point of the app. Bulk-keeping unlooked-at photos is how an
  archive fills with mediocre frames.
- Bulk discard must be undoable as a single unit — one `u` reverses the whole
  batch, not one photo at a time.

## 5. Review marks

Every thumbnail, in both strip and grid, carries a small corner mark:

| State | Mark |
|---|---|
| unreviewed | no mark at all |
| kept | tick, keep green |
| kept + great | tick, great gold |
| discarded | tick, discard red |

A tick for all reviewed states, with colour carrying the verdict — so "have I
looked at this" is answerable from mark *presence* alone, without reading
colour.

Marks must stay legible at the smallest thumbnail size, against both dark and
bright photos. Give them a background or outline; don't rely on the photo
behind them.

## 6. Resume

- Opening an existing session starts at the **first unreviewed photo**, with
  the strip scrolled there.
- The user can jump backwards (to redo a session they don't trust) or forwards
  (to skip a run known to be bad). The grid is the mechanism for this — no
  dedicated "jump to next unreviewed" key is needed.
- After a backward jump, `space` advances **sequentially**, not back to the
  furthest unreviewed point.
- **Reviewed** means the photo has a verdict. Scrolling past it does not count.

### 6.1 Files already in the output folder

**Skip on match.** If a file already exists in the destination and its size
matches, skip it silently — no re-copy, no prompt. If it exists but the size
differs, treat it as a failed copy from a crashed session and re-copy it.

## 7. Technical decisions

**Date source.** EXIF `DateTimeOriginal`, not file modification time. The
prototype uses `file.lastModified`, which is wrong — mtime changes when files
are copied. Fall back to mtime only where EXIF is absent, and mark those files
as uncertain.

**Photo identity.** Review progress must survive across sessions, and OM-1
filenames roll over and repeat between cards. Choose a stable identifier
(filename stem + EXIF timestamp, or a content hash) and state the choice and
its cost in the plan.

**State storage.** Per-photo review state is persistent, must survive the app
closing mid-session, and must not live inside the input folder — that is
read-only. Say where it lives and why.

**Two cache tiers, kept separate:**

| Cache | Long edge | Used by |
|---|---|---|
| thumbnails | ~200px | strip and grid |
| previews | ~2000px | main photo view |

Do not reuse the preview cache for thumbnails.

**Virtualisation is required** in both strip and grid. A session may be 1500+
photos and a grid can show 200+ at once. Render only what is near the viewport.

**Lazy generation, outward from the current photo** in capture order — so the
strip fills in around where work is happening, not from photo 1. Show
placeholders for thumbnails not yet generated. Never block on generation.

## 8. Retained constraints

- Input folder is read-only. Never write to it, never delete from it.
- Nothing is ever deleted anywhere. Discards are simply not copied.
- Default to copying raws, not moving.
- Every keyboard action needs a visible clickable equivalent.
- Verdict keys must call `preventDefault()` — otherwise the keystroke lands in
  the tag field that just took focus.

## 9. Still open

- **Non-contiguous dates produce a misleading range name.** Picking the 3rd and
  the 19th yields `2026-07-03 - 2026-07-19 Spurn`, implying seventeen days that
  aren't there. The editable folder name covers it, but flag if a better rule
  suggests itself.
- Whether the persistent verdict-button cursor causes accidental discards.
- Whether "Discard" reads as too final and causes hesitation.
