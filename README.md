# Winnow

Desktop app for culling and tagging bird and wildlife photographs. pywebview shell over a Python backend, with a vanilla HTML/CSS/JS front-end (no build step).

To winnow is to separate grain from chaff, which is the culling operation itself. It's also the drumming display flight of a snipe, made by air through the outer tail feathers.

## What it does

Ingests RAW+JPEG pairs from an SD card. You cull and tag one photo at a time (keep, keep and mark great, or discard), then it copies the kept RAWs to a destination folder and writes XMP sidecars alongside them, which allows future querying. 


## Requirements

- macOS
- Python 3.8+
- [exiftool](https://exiftool.org) — `brew install exiftool`

## Setup

```sh
pip install -r requirements.txt
python3 main.py
```

## Layout

```
winnow/       Python package (backend, exposed to the front-end via pywebview's js_api)
frontend/     HTML/CSS/JS UI, loaded directly, no build step
data/         Species tag vocabulary (*-tags.json), see docs/SPEC.md §7
assets/       App icon source images
docs/         Build spec, session-flow/navigation spec, and the validated interaction prototype
```

Design constraints and conventions: [`CLAUDE.md`](CLAUDE.md). Full build
spec: [`docs/SPEC.md`](docs/SPEC.md). Screen-by-screen navigation:
[`docs/SESSION-FLOW.md`](docs/SESSION-FLOW.md).

## License

MIT — see [`LICENSE`](LICENSE). The bundled fonts under `frontend/fonts/`
keep their own licenses (SIL Open Font License / GUST Font License); see the
license files alongside them there.
