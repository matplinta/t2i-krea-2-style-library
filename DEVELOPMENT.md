# Generation and Development Guide

This guide covers local generation, preview, validation, and static deployment for the [Krea 2 Style Library](README.md).

## Project layout

```text
assets/                       Browser CSS and JavaScript
comfyui_workflows/            ComfyUI API workflow used for generation
data/styles.json              Canonical style names, descriptors, and categories
data/base_prompts.json        Base prompts, fixed seeds, dimensions, and prompt template
data/generation_manifest.json Resumable generation state consumed by the viewer
images/                       Generated images grouped by base-prompt id
scripts/generate_images.py    ComfyUI API batch generator
tests/                        Data, workflow, and viewer validation
index.html                    Static viewer
```

## Preview the site

From the repository root:

```powershell
python -m http.server 8000
```

Open <http://localhost:8000/> and stop the server with `Ctrl+C`.

Opening `index.html` directly with `file://` is not supported because the viewer loads JSON with `fetch`, matching GitHub Pages and Cloudflare Pages behavior.

## Configure base prompts

Edit `data/base_prompts.json`. Every enabled prompt defines one comparison set: an unstyled base image and one image per selected style. All images in that set use the prompt's seed and dimensions.

```json
{
  "schema_version": 1,
  "prompt_template": "Subject: {base_prompt}\n\nStyle: {style_name}. {style_descriptor}",
  "prompts": [
    {
      "id": "portrait",
      "label": "Portrait",
      "prompt": "Your common subject prompt.",
      "seed": 123456789,
      "width": 1024,
      "height": 1536,
      "enabled": true
    }
  ]
}
```

IDs become folder names and manifest keys. Use lowercase letters, numbers, and hyphens. Set `enabled` to `false` to retain a prompt without displaying or generating it.

The prompt template supports `{base_prompt}`, `{style_name}`, and `{style_descriptor}`. Changing a prompt, seed, dimensions, or template does not replace an existing file automatically; use `--overwrite` when regeneration is intentional.

Different base prompts may use different aspect ratios. Width and height are passed to the workflow's `ResolutionMaster` node.

## ComfyUI requirements

The generator uses `comfyui_workflows/Krea2_Basic_api.json`. Confirm that its models, custom nodes, and LoRAs load successfully, generate one image manually, and keep ComfyUI available at `http://127.0.0.1:8188`.

The script discovers these workflow nodes automatically:

- Positive prompt: `CLIPTextEncode`
- Sampler: `KSampler`
- Linked seed: `Seed (rgthree)`
- Dimensions: `ResolutionMaster`
- Output: `SaveImage`

Explicit node-ID options are available if a modified workflow contains multiple candidates. Run `python scripts/generate_images.py --help` for the complete CLI reference.

## Output formats

PNG is the default. The generator writes ComfyUI's returned bytes without decoding or re-encoding them, preserving embedded PNG metadata, including the API `prompt` graph. The API-only workflow does not provide the UI canvas `workflow` metadata chunk.

```powershell
python scripts/generate_images.py
```

WebP is smaller but does not retain ComfyUI PNG metadata. It requires Pillow:

```powershell
python -m pip install -r requirements.txt
python scripts/generate_images.py --image-format webp
```

Use `--webp-quality 1-100` to override the default quality of 88. PNG and WebP are separate outputs; always use the same `--image-format` when checking or resuming a batch.

## Plan and generate

Validate configuration and inspect the remaining workload without connecting to ComfyUI:

```powershell
python scripts/generate_images.py --dry-run
```

For WebP output, include the format so the dry run checks the correct files:

```powershell
python scripts/generate_images.py --dry-run --image-format webp
```

Run a two-image pilot—the unstyled base and first style:

```powershell
python scripts/generate_images.py --limit 2 --max-in-flight 1
```

Run every enabled base prompt:

```powershell
python scripts/generate_images.py --max-in-flight 1
```

Select one or several base prompts by ID or exact label:

```powershell
python scripts/generate_images.py --base-prompt portrait --max-in-flight 1

python scripts/generate_images.py `
  --base-prompt portrait `
  --base-prompt full-figure `
  --base-prompt architecture `
  --max-in-flight 1
```

Select styles by ID or exact name; both options are repeatable:

```powershell
python scripts/generate_images.py --style anime-style
python scripts/generate_images.py --style "Anime Style"
```

Other useful options:

```powershell
# Intentionally regenerate an existing selection
python scripts/generate_images.py --base-prompt portrait --style anime-style --overwrite

# Use another ComfyUI address
python scripts/generate_images.py --comfy-url http://127.0.0.1:8189
```

`--limit` applies to the assembled job list. Do not use it for a complete overnight run.

## Files, manifest, and resuming

Outputs use these paths:

```text
images/<base-prompt-id>/base.png
images/<base-prompt-id>/<style-id>.png
```

WebP output uses the same layout with `.webp`. The manifest is updated whenever a job is queued, completed, or fails. Files are written through a temporary `.part` path and moved into place only when complete.

Stop a run with `Ctrl+C`. Restart the same command without `--overwrite`; non-empty existing outputs are skipped. Keep the format and output options identical to the original run. An image active in ComfyUI at interruption may be regenerated because it might finish there without being downloaded. With `--max-in-flight 1`, this affects at most one image.

ComfyUI also retains its normal output copy. This project never deletes files from the ComfyUI output directory.

## Viewer behavior

The base-prompt selector changes the active comparison set globally. **View prompt** shows the exact base text, while **Show base image** reveals the unstyled reference. Search, category, sorting, favorites, card details, and grid-density preferences operate entirely in the browser. Clicking an image opens the full-size viewer.

Favorites are stored under `krea2-style-library-favorites-v2`. JSON exports intentionally contain only `name`, `descriptor`, and `categories`—not seeds, base prompts, paths, or generation metadata.

## Validate the project

```powershell
python -m unittest discover -s tests -v
```

The suite validates catalog integrity, base-prompt configuration, workflow discovery and mutation, output handling, generation planning, and required viewer behavior.

## Static deployment

No build step or backend is required. Serve the repository root through GitHub Pages or Cloudflare Pages.

For GitHub Pages, choose **Settings → Pages → Deploy from a branch**, then select `main` and `/(root)`. The current deployment is available at:

<https://matplinta.github.io/t2i-krea-2-style-library/>

Commit generated images together with `data/generation_manifest.json`; the viewer uses the manifest to resolve each selected image.
