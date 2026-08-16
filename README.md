# Krea 2 Style Library

A static visual catalog for comparing prompt-defined Krea 2 styles against the same base image prompt. The project contains 286 unique style descriptors, a ComfyUI API batch generator, and a browser-only viewer with category filters and locally stored favorites.

The catalog is based on the style descriptors originally shared in [this Stable Diffusion Reddit post](https://www.reddit.com/r/StableDiffusion/comments/1uzdj7o/krea_2_styles_wildcards_txt/).

## Project layout

```text
assets/                       Browser CSS and JavaScript
comfyui_workflows/            The ComfyUI API workflow used for generation
data/styles.json              Canonical style names, descriptors, and categories
data/base_prompts.json        Base prompts, fixed seeds, and prompt template
data/generation_manifest.json Resumable generation state used by the viewer
images/                       Generated web images grouped by base-prompt id
scripts/generate_images.py    ComfyUI API batch generator
tests/                        Data and workflow validation
index.html                    Static viewer
```

No backend is required. Favorites remain in the visitor's browser and are never sent to a server.

## Preview the site locally

Run this command from the project directory:

```powershell
python -m http.server 8000
```

Then open <http://localhost:8000/>. Stop the server with `Ctrl+C`.

Opening `index.html` directly with `file://` is not supported because the page loads its catalog files with `fetch`, matching how it will work on GitHub Pages or Cloudflare Pages.

## Configure base prompts

Edit `data/base_prompts.json`. Each enabled entry creates one complete comparison set: one unstyled base image followed by one image for every selected style. The reference and all styled images use the same seed and dimensions. Different base prompts can use different aspect ratios.

```json
{
  "schema_version": 1,
  "prompt_template": "{base_prompt}\n\nStyle: {style_name}. {style_descriptor}",
  "prompts": [
    {
      "id": "portrait",
      "label": "Portrait",
      "prompt": "Your complete common portrait prompt goes here.",
      "seed": 123456789,
      "width": 1024,
      "height": 1536,
      "enabled": true
    },
    {
      "id": "landscape",
      "label": "Landscape",
      "prompt": "Your complete common landscape prompt goes here.",
      "seed": 987654321,
      "width": 1536,
      "height": 1024,
      "enabled": true
    }
  ]
}
```

IDs become folder names, so use lowercase letters, numbers, and hyphens. An ID should not be changed after generating its images unless you intend to generate that set again. Width and height are positive pixel values passed to the workflow's ResolutionMaster node. If you change the dimensions of a prompt that already has images, regenerate it with `--overwrite`.

The prompt template supports:

- `{base_prompt}`
- `{style_descriptor}`
- `{style_name}`

Change their order or surrounding wording in the template if testing shows that Krea 2 responds better to a different composition.

Set `enabled` to `false` to keep a prompt definition without displaying or generating it.

## ComfyUI requirements

The generator uses `comfyui_workflows/Krea2_Basic_api.json`. Its default resolution is 1024×1536, but each base prompt can override it. The script discovers and uses these nodes automatically:

- Positive prompt: `CLIPTextEncode`, node `6`
- Sampler: `KSampler`, node `2`
- Linked seed: `Seed (rgthree)`, node `17`
- Dimensions: `ResolutionMaster`, node `16`
- Output: `SaveImage`, node `19`

The script discovers these by class and title, so it can tolerate changed node IDs when each required node remains unambiguous. Explicit node-id command options are available if a later workflow contains multiple candidates.

Before running a batch:

1. Open the workflow in ComfyUI and confirm that all models, custom nodes, and LoRAs load.
2. Generate one image manually in ComfyUI.
3. Ensure ComfyUI is available at `http://127.0.0.1:8188`.

The workflow currently depends on the Krea 2 UNET and text encoder, the configured VAE, ResolutionMaster, and rgthree nodes shown in the workflow itself.

## PNG output and ComfyUI metadata

Generated images are stored as PNG files exactly as returned by ComfyUI's `SaveImage` node. The generator does not decode, resize, optimize, or re-encode them, so any embedded ComfyUI metadata remains in the PNG text chunks.

With the current API-only workflow, ComfyUI emits a `prompt` metadata chunk containing the executed API graph and complete composed prompt. It does not emit the UI-only `workflow` chunk used to reconstruct the canvas layout, because the non-API workflow is intentionally not part of this project. The generator preserves every metadata chunk that ComfyUI does return.

PNG generation uses only Python's standard library. Do not run metadata-bearing PNGs through an image optimizer if you need to preserve their ComfyUI metadata; many optimization and format-conversion tools remove ancillary PNG chunks.

WebP is available as an explicit smaller-file alternative. It requires Pillow and does **not** preserve ComfyUI's PNG metadata:

```powershell
python -m pip install -r requirements.txt
python scripts/generate_images.py --image-format webp
```

Use `--webp-quality 1-100` to change the default quality of 88. Omitting `--image-format` always produces metadata-preserving PNG files.

## Generate images

First validate the configuration and inspect the planned workload without connecting to ComfyUI. Dry-run separates the complete selection into existing outputs that will be skipped and outputs that still need generation:

```powershell
python scripts/generate_images.py --dry-run
```

Run a two-image pilot (the unstyled base image and the first style):

```powershell
python scripts/generate_images.py --limit 2 --max-in-flight 1
```

After checking those images, run the complete configured matrix:

```powershell
python scripts/generate_images.py
```

Useful targeted commands:

```powershell
# One base prompt
python scripts/generate_images.py --base-prompt portrait

# One style, selected by id or exact name
python scripts/generate_images.py --style anime-style
python scripts/generate_images.py --style "Anime Style"

# Regenerate an existing selection
python scripts/generate_images.py --base-prompt portrait --style anime-style --overwrite

# Use a different ComfyUI address
python scripts/generate_images.py --comfy-url http://127.0.0.1:8189
```

Run `python scripts/generate_images.py --help` for all options.

### Resuming and failures

The unstyled reference is written to `images/<base-prompt-id>/base.png`; styled outputs use `images/<base-prompt-id>/<style-id>.png`. `data/generation_manifest.json` is updated after each queued, completed, or failed job.

When `--image-format webp` is selected, the extension is `.webp` instead. PNG and WebP files are treated as separate outputs, so changing formats generates the selected format without overwriting the other copy.

Running the same command again skips image files that already exist. Failed or interrupted jobs without an output file are queued again. Use `--overwrite` only when you intentionally want to replace completed images.

ComfyUI's `SaveImage` node also retains its normal copy under the ComfyUI output directory. This project does not delete files outside the repository.

## Viewer behavior

The base-prompt selector changes the image variant globally across the entire grid. **View prompt**, beside that selector, opens the exact configured base text. The unstyled reference is hidden by default; **Show base image** displays it as the first card for direct comparison. This preference is stored locally, and the reference is not included in favorites, filtering, or exports. Cards automatically adopt the selected prompt's portrait, square, or landscape aspect ratio. Search covers names, descriptors, and categories. Category and favorites-only filters can be combined, and sorting supports original order, alphabetical order, or favorites first. Descriptors and categories are hidden by default; **Show descriptors & categories** reveals them, and this display preference is stored in the browser.

The **Images per row** slider controls desktop grid density from 2 to 8 columns and stores the preference in the browser. Responsive layouts progressively cap the effective grid at 4, 3, 2, and finally 1 column as the viewport narrows.

The copy icon beside each card title copies `<style name>. <style descriptor>` to the clipboard, matching the style portion of the configured prompt template.

The heart appears in the top-right corner of an image when its card is hovered, focused, or already favorited. On touch devices it remains visible. Favorites use the browser key `krea2-style-library-favorites-v2`.

The compact **Export** menu in the header offers all styles or favorites-only JSON. Both exports contain only:

```json
{
  "name": "Anime Style",
  "descriptor": "...",
  "categories": ["Anime & Manga", "Illustration"]
}
```

They intentionally omit base prompts, seeds, generation metadata, and image paths.

## Validate the project

```powershell
python -m unittest discover -s tests
```

The checks cover catalog uniqueness and count, removed records, Film Noir naming, contiguous ordering, workflow-node discovery, linked-seed handling, workflow resolution, and removal of the legacy editor UI.

## Static hosting

The repository can be published as a plain static directory. GitHub Pages and Cloudflare Pages need no build command; serve the repository root as the site root. Run the local preview command before publishing to verify that every configured prompt set has its generated images.
