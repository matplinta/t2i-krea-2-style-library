# AGENTS.md

Guidance for AI coding agents working in this repository. Human-facing docs live in [README.md](README.md) and [DEVELOPMENT.md](DEVELOPMENT.md); read DEVELOPMENT.md for the full generator CLI.

## What this is

A fully static style-comparison viewer for Krea 2 (no build step, no backend), plus a Python batch generator that renders the images through a local ComfyUI instance. Deployed as-is from the repository root to GitHub Pages: <https://matplinta.github.io/t2i-krea-2-style-library/>.

## Commands

```powershell
python -m unittest discover -s tests -v                          # full test suite (stdlib only)
python -m http.server 8000                                       # preview at http://localhost:8000/ (file:// does not work: the viewer uses fetch)
python scripts/generate_images.py --dry-run --image-format webp  # plan without contacting ComfyUI
python scripts/generate_images.py --image-format webp --style <style-id> --max-in-flight 1
```

- **Always pass `--image-format webp`.** All committed images are `.webp`; the generator defaults to PNG and would treat every image as missing. WebP requires Pillow (`requirements.txt`).
- ComfyUI runs at `http://127.0.0.1:8188`. Generation is slow; run it in the background and verify the `Complete: N | Skipped: N | Failed: N` summary line.
- Without `--overwrite`, existing non-empty outputs are skipped, so re-running a command resumes it.
- Node.js is not installed on this machine, so `node`/`npx` checks are unavailable and the Playwright MCP plugin (which launches via `npx`) cannot start.

## Layout

| Path | Role |
|---|---|
| `index.html`, `assets/app.js`, `assets/app.css` | The entire viewer. Vanilla JS in one IIFE, no dependencies. |
| `data/styles.json` | Canonical catalog: `id`, `order`, `name`, `descriptor`, `categories`. |
| `data/base_prompts.json` | Base prompts (seed, width, height, `enabled`) and the `prompt_template`. |
| `data/generation_manifest.json` | Written by the generator; the viewer resolves image paths from it. |
| `images/<base-prompt-id>/<style-id>.webp` | Generated images; `base.webp` is the unstyled reference. |
| `scripts/generate_images.py` | ComfyUI API batch generator; validates the catalog in `load_styles()`. |
| `comfyui_workflows/Krea2_Basic_api.json` | Workflow graph; nodes are discovered by class type. |
| `tests/test_project.py` | Catalog, workflow, generator, and viewer checks (many are string assertions on the HTML/JS/CSS). |

## Data invariants

- Style `id`s and base-prompt `id`s: lowercase letters, digits, single hyphens. They become file names and manifest keys (`<prompt-id>/<style-id>`).
- Style `order` must be contiguous `1..N`. Descriptors must be unique after whitespace normalisation and case-folding.
- The style name is part of the prompt (`Style: {style_name}. {style_descriptor}`), so renaming a style changes its output.
- Categories must be one of the existing 15 (Illustration, Photography, Anime & Manga, Painting & Fine Art, Character & Concept, Comics & Graphic Novels, Cartoon & Animation, Drawing & Sketch, Design & Posters, 3D & Render, Cinema & Lighting, Craft & Material, Commercial & Editorial, Gaming, Printmaking & Graphic Art). Ask before inventing a new one.
- The JSON data files use 2-space indent, `ensure_ascii=False`, CRLF line endings and a trailing CRLF. Rewrite them with `json.dumps(data, indent=2, ensure_ascii=False).replace('\n', '\r\n') + '\r\n'` so diffs stay minimal; confirm the round trip is byte-identical before writing.

## Common tasks

**Add a style**
1. Append it to `data/styles.json` with the next `order`.
2. Update the hard-coded catalog count in `tests/test_project.py` (`CatalogTests`: three `len(...)` asserts plus `range(1, N + 1)`) and the count in the first paragraph of `README.md`.
3. Run the tests and a `--dry-run` for that `--style`; expect one output per enabled base prompt.
4. Generate (the user must have ComfyUI running), then commit the images together with `data/generation_manifest.json`.

**Remove a style**: delete its entry and renumber `order`; delete `images/*/<style-id>.webp`; delete its `<prompt-id>/<style-id>` keys from the manifest; update the test and README counts. A dry run over all styles should then report `Outputs to generate: 0`. Favourites pointing at removed ids are pruned automatically on page load (`init()` in `app.js`).

## Viewer conventions

- Persisted preferences use `localStorage` keys named `krea2-style-library-<name>-v<N>`, each with its own `load…Preference`/`save…Preference` pair wrapped in `try/catch`, and the page must work without storage. Never change the favourites key (`krea2-style-library-favorites-v2`) or its format (a JSON array of style ids): that would wipe users' favourites.
- New header toggles go in `#header-options` as `<label class="toggle">`. Under the mobile breakpoint the options form a two-column grid; full-width items are listed in the `.header-options > .details-toggle, …` rule in `app.css`.
- Favourite toggling must not call `render()` (a test enforces this; re-rendering causes a visible blink).
- JSON exports deliberately contain only `name`, `descriptor` and `categories`.
- `tests/test_project.py` asserts specific literals in the source (e.g. `` `${style.name}. ${style.descriptor}` ``, element ids, CSS selectors). When refactoring the viewer, run the tests and keep or deliberately update those strings.
- `assets/app.js` and `app.css` are linked without version strings. Browsers (Firefox especially) can keep a stale `app.js` alongside a fresh `index.html`, so a new control may appear to do nothing. Hard-reload (Ctrl+Shift+R) before debugging front-end changes.

## Verifying changes

- Run the test suite after every change.
- For UI changes, also check in a real browser via the local server: open the page, exercise the control, reload to confirm persistence, and look for console errors. Use a port other than the user's own server and clean up any `localStorage` keys you set during testing.
- Don't leave helper or test-harness files in the repo root: it is deployed as-is.

## Git

- `master` is the main branch. Commit only when asked.
- Commit generated images and `data/generation_manifest.json` together.
