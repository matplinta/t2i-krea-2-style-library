# Krea 2 Style Library

[**Open the live style library**](https://matplinta.github.io/t2i-krea-2-style-library/)

A static visual reference for comparing 286 prompt-defined styles with Krea 2. Each comparison set holds the subject, seed, and dimensions constant, making the effect of the style descriptor easier to inspect across portrait, landscape, square, and panoramic compositions.

The project grew out of a practical problem: long style lists are useful as wildcards, but difficult to evaluate from text alone. This library turns them into a browsable matrix generated locally through ComfyUI.

## What is included

- Multiple globally selectable base prompts and an optional unstyled reference image
- Search, category filtering, sorting, adjustable grid density, and full-image viewing
- Browser-local favorites with favorites-only filtering
- One-click copying of each style name and descriptor
- JSON export for the complete catalog or favorites
- A resumable ComfyUI batch generator with PNG and WebP output

The viewer is fully static. Favorites and display preferences remain in browser storage; there is no application backend.

## Generation

The repository includes the ComfyUI API workflow, normalized style catalog, base-prompt configuration, generation manifest, and Python batch generator used to build the library.

See [DEVELOPMENT.md](DEVELOPMENT.md) for configuration, generation commands, resuming batches, local preview, validation, and deployment.

## Credits

The style descriptors are based on prompts shared by the original contributor in [KREA 2 Styles / Wildcards.txt on Reddit](https://www.reddit.com/r/StableDiffusion/comments/1uzdj7o/krea_2_styles_wildcards_txt/). Many thanks to them for assembling and publishing the source list that made this visual reference possible.
