# Winnow

Desktop app (macOS) for culling and tagging bird photographs. pywebview shell +
Python backend + vanilla HTML/CSS/JS front-end. Single user.

Full build spec: `docs/SPEC.md`. Read it before starting a new build step.
Session flow and navigation: `docs/SESSION-FLOW.md` — supersedes docs/SPEC.md
§5–6 on the start screen and cull-screen navigation.
Validated interaction design: `docs/prototype.html` — reproduce its behaviour,
don't reinvent it. Its dot strip and single-folder start screen are superseded.

## Hard constraints

These came from the user finding darktable's interface overwhelming. They are
constraints, not preferences.

- One screen, one job. No permanently visible side panels. The cull screen shows
  a photo, three verdict buttons, and a tag field. Nothing else.
- Settings live behind a settings screen, never on the main canvas.
- Every keyboard action needs a visible clickable equivalent. The mouse-only
  path must be complete, including finishing a session.
- Never present a blank state — species carries over from the previous photo.
- Nothing is ever deleted. Discards are left in place or copied elsewhere.
  Undo always available.
- A new feature must not add a control to the cull screen. If it would, it goes
  on another screen or doesn't ship. The thumbnail strip is the single
  exception, because it reports state rather than offering controls.
- Bulk actions are discard-only. Never bulk keep, never bulk tag — keeping is
  what triggers tagging, and tagging is the point of the app.

## Do not build yet

No bird detection, no species ID, no ML of any kind. v1 is the manual workflow
only. The suggestion row in the tag field is the socket the model will fill
later; leave it in place and leave it empty. See docs/SPEC.md §9.

## Gotchas

- Verdict keys (`space`, `g`, `x`) must call `preventDefault()`. Without it the
  keystroke lands in the tag field that just took focus. This was a real bug.
- Species tags are multi-valued. A photo can contain more than one species.
  Never model this as a single field.
- "Great" is written as `xmp:Rating` = 5, not a keyword — other tools read it.
- Input folder is read-only. Never write to or delete from it.
- Default to copying raws, not moving. Moving off an SD card before verifying
  the output is a data-loss risk.
- Don't load full-size JPEGs into the webview; use the downscaled preview cache.

## Conventions

- `exiftool` via subprocess for all metadata. Not a Python XMP library.
- No build step on the front-end. Don't introduce React without a concrete reason.
- Sentence case in all UI copy.
