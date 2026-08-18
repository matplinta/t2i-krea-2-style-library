import argparse
import copy
import json
import tempfile
import unittest
from pathlib import Path

from scripts import generate_images


ROOT = Path(__file__).resolve().parents[1]


class CatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.styles = generate_images.load_styles(ROOT / "data" / "styles.json")

    def test_catalog_has_expected_unique_styles(self):
        self.assertEqual(len(self.styles), 286)
        self.assertEqual(len({style["id"] for style in self.styles}), 286)
        self.assertEqual(len({style["descriptor"].casefold() for style in self.styles}), 286)

    def test_removed_and_renamed_records(self):
        names = {style["name"] for style in self.styles}
        self.assertNotIn("Romance Manga", names)
        self.assertNotIn("Lego", names)
        self.assertNotIn("Borderlands", names)
        self.assertNotIn("Film Noir", names)
        self.assertIn("Film Noir 1", names)
        self.assertIn("Film Noir 2", names)

    def test_orders_are_contiguous(self):
        self.assertEqual([style["order"] for style in self.styles], list(range(1, 287)))


class WorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow_path = ROOT / "comfyui_workflows" / "Krea2_Basic_api.json"
        cls.workflow = json.loads(cls.workflow_path.read_text(encoding="utf-8"))
        cls.args = argparse.Namespace(
            prompt_node_id=None,
            sampler_node_id=None,
            save_node_id=None,
            resolution_node_id=None,
        )

    def test_current_workflow_nodes_are_discovered(self):
        nodes = generate_images.discover_workflow_nodes(self.workflow, self.args)
        self.assertEqual(nodes.prompt, "6")
        self.assertEqual(nodes.sampler, "2")
        self.assertEqual(nodes.save_image, "19")
        self.assertEqual(nodes.resolution, "16")

    def test_current_workflow_resolution(self):
        self.assertEqual(generate_images.workflow_resolution(self.workflow), (1024, 1536))

    def test_linked_seed_node_is_updated(self):
        workflow = copy.deepcopy(self.workflow)
        generate_images.set_workflow_seed(workflow, "2", 123456789)
        self.assertEqual(workflow["17"]["inputs"]["seed"], 123456789)
        self.assertEqual(workflow["2"]["inputs"]["seed"], ["17", 0])

    def test_prompt_template_combines_base_and_descriptor(self):
        style = {"name": "Example", "descriptor": "ink drawing"}
        base = {"prompt": "a red bicycle"}
        result = generate_images.compose_prompt(
            "{base_prompt}\nStyle: {style_descriptor}", base, style
        )
        self.assertEqual(result, "a red bicycle\nStyle: ink drawing")

    def test_job_preparation_uses_linked_seed_and_deterministic_prefix(self):
        style = {
            "id": "ink-drawing",
            "name": "Ink Drawing",
            "descriptor": "fine black ink lines",
        }
        base = {
            "id": "portrait",
            "label": "Portrait",
            "prompt": "portrait of a traveler",
            "seed": 42,
            "width": 1280,
            "height": 720,
        }
        jobs = generate_images.create_jobs(
            [style],
            [base],
            "{base_prompt}\n\n{style_descriptor}",
            ROOT / "images",
            "png",
        )
        self.assertEqual(len(jobs), 2)
        base_job, style_job = jobs
        self.assertIsNone(base_job.style)
        self.assertEqual(base_job.full_prompt, "portrait of a traveler")
        self.assertEqual(base_job.relative_output_path, "images/portrait/base.png")
        self.assertEqual(style_job.relative_output_path, "images/portrait/ink-drawing.png")
        nodes = generate_images.discover_workflow_nodes(self.workflow, self.args)
        prepared = generate_images.prepare_workflow(self.workflow, nodes, style_job)
        self.assertEqual(prepared["6"]["inputs"]["text"], "portrait of a traveler\n\nfine black ink lines")
        self.assertEqual(prepared["17"]["inputs"]["seed"], 42)
        self.assertEqual(prepared["16"]["inputs"]["width"], 1280)
        self.assertEqual(prepared["16"]["inputs"]["height"], 720)
        self.assertEqual(
            prepared["19"]["inputs"]["filename_prefix"],
            "krea2-style-library/portrait/ink-drawing",
        )

        base_prepared = generate_images.prepare_workflow(self.workflow, nodes, base_job)
        self.assertEqual(base_prepared["6"]["inputs"]["text"], "portrait of a traveler")
        self.assertEqual(
            base_prepared["19"]["inputs"]["filename_prefix"],
            "krea2-style-library/portrait/base",
        )

    def test_webp_is_an_explicit_cli_option(self):
        parser = generate_images.build_parser()
        self.assertEqual(parser.parse_args([]).image_format, "png")
        self.assertEqual(parser.parse_args(["--image-format", "webp"]).image_format, "webp")
        jobs = generate_images.create_jobs(
            [{"id": "ink", "name": "Ink", "descriptor": "ink"}],
            [{
                "id": "portrait",
                "label": "Portrait",
                "prompt": "portrait",
                "seed": 1,
                "width": 1024,
                "height": 1536,
            }],
            "{base_prompt} {style_descriptor}",
            ROOT / "images",
            "webp",
        )
        self.assertEqual(jobs[0].relative_output_path, "images/portrait/base.webp")
        self.assertEqual(jobs[1].relative_output_path, "images/portrait/ink.webp")

    def test_png_bytes_are_preserved_exactly(self):
        png_with_metadata = generate_images.PNG_SIGNATURE + b"ComfyUI metadata test payload"
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "image.png"
            generate_images.save_comfy_png(png_with_metadata, destination)
            self.assertEqual(destination.read_bytes(), png_with_metadata)

    def test_dry_run_planning_distinguishes_existing_outputs(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "style.png"
            job = generate_images.GenerationJob(
                key="portrait/example",
                style={"id": "example", "name": "Example"},
                base_prompt={"id": "portrait"},
                full_prompt="example prompt",
                seed=1,
                width=1024,
                height=1536,
                output_path=destination,
                relative_output_path="images/portrait/example.png",
                prompt_sha256="hash",
            )
            pending, existing = generate_images.pending_jobs([job])
            self.assertEqual(pending, [job])
            self.assertEqual(existing, [])

            destination.write_bytes(b"complete")
            pending, existing = generate_images.pending_jobs([job])
            self.assertEqual(pending, [])
            self.assertEqual(existing, [job])

            pending, existing = generate_images.pending_jobs([job], overwrite=True)
            self.assertEqual(pending, [job])
            self.assertEqual(existing, [])


class SiteTests(unittest.TestCase):
    def test_legacy_editor_language_is_absent(self):
        content = (ROOT / "index.html").read_text(encoding="utf-8").casefold()
        self.assertNotIn("browser editor", content)
        self.assertNotIn("images missing", content)
        self.assertNotIn("local edits", content)
        self.assertNotIn("needs review", content)

    def test_base_prompt_config_is_valid(self):
        config, enabled = generate_images.load_base_prompt_config(
            ROOT / "data" / "base_prompts.json"
        )
        self.assertEqual(config["schema_version"], 1)
        self.assertIsInstance(config["prompts"], list)
        self.assertTrue(all(prompt in config["prompts"] for prompt in enabled))
        self.assertTrue(
            all(
                isinstance(prompt.get("width"), int) and isinstance(prompt.get("height"), int)
                for prompt in enabled
            )
        )

    def test_prompt_viewer_and_style_copy_controls_are_present(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        javascript = (ROOT / "assets" / "app.js").read_text(encoding="utf-8")
        self.assertIn('id="view-base-prompt"', html)
        self.assertIn('id="base-prompt-dialog"', html)
        self.assertLess(
            html.index('id="base-prompt"'),
            html.index('id="view-base-prompt"'),
        )
        self.assertLess(
            html.index('id="view-base-prompt"'),
            html.index('id="category-filter"'),
        )
        self.assertIn("`${style.name}. ${style.descriptor}`", javascript)
        self.assertIn("copy-style-button", javascript)

    def test_filter_controls_have_visible_labels(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        for control_id in ("search", "base-prompt", "category-filter", "sort"):
            self.assertIn(f'for="{control_id}"', html)

    def test_compact_header_options_and_export_menu_are_present(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertNotIn('class="utility-row"', html)
        self.assertIn('class="header-options"', html)
        self.assertIn('class="export-menu"', html)
        self.assertLess(html.index("Prompt style reference"), html.index('class="header-options"'))
        self.assertLess(html.index('class="header-options"'), html.index('id="library-summary"'))
        self.assertLess(html.index('class="export-menu"'), html.index('id="export-all"'))
        self.assertLess(html.index('id="export-all"'), html.index('id="export-favorites"'))

    def test_card_details_visibility_toggle_is_present(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        javascript = (ROOT / "assets" / "app.js").read_text(encoding="utf-8")
        stylesheet = (ROOT / "assets" / "app.css").read_text(encoding="utf-8")
        self.assertIn('id="show-card-details"', html)
        self.assertNotIn('id="show-card-details" type="checkbox" aria-controls="catalog" checked', html)
        self.assertIn("CARD_DETAILS_KEY", javascript)
        self.assertIn("showCardDetails: false", javascript)
        self.assertIn("details-hidden", stylesheet)

    def test_responsive_grid_density_and_image_ratios_are_present(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        javascript = (ROOT / "assets" / "app.js").read_text(encoding="utf-8")
        stylesheet = (ROOT / "assets" / "app.css").read_text(encoding="utf-8")
        self.assertIn('id="grid-columns"', html)
        self.assertIn('id="grid-columns" type="range" min="1" max="8"', html)
        self.assertIn("GRID_COLUMNS_KEY", javascript)
        self.assertIn("Math.max(1, value)", javascript)
        self.assertIn("$('#grid-columns').max = String(columnCap)", javascript)
        self.assertIn("imageWrap.style.aspectRatio", javascript)
        self.assertIn("repeat(var(--columns, 5)", stylesheet)
        self.assertNotIn("if (window.innerWidth <= 420) return 1", javascript)
        self.assertNotIn("@media (max-width: 420px)", stylesheet)

    def test_mobile_header_controls_are_collapsible(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        javascript = (ROOT / "assets" / "app.js").read_text(encoding="utf-8")
        stylesheet = (ROOT / "assets" / "app.css").read_text(encoding="utf-8")
        self.assertIn('id="mobile-menu-toggle"', html)
        self.assertIn('aria-expanded="false"', html)
        self.assertIn('aria-controls="header-options library-filters"', html)
        self.assertIn("mobile-menu-open", javascript)
        self.assertIn(".mobile-menu-open .header-options", stylesheet)
        self.assertIn(".mobile-menu-open .toolbar", stylesheet)

    def test_unstyled_base_image_has_an_off_by_default_toggle(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        javascript = (ROOT / "assets" / "app.js").read_text(encoding="utf-8")
        self.assertIn('id="show-base-image"', html)
        self.assertNotIn('id="show-base-image" type="checkbox" aria-controls="catalog" checked', html)
        self.assertIn("const BASE_IMAGE_ID = 'base'", javascript)
        self.assertIn("const SHOW_BASE_IMAGE_KEY", javascript)
        self.assertIn("showBaseImage: false", javascript)
        self.assertIn(
            "if (state.showBaseImage && activePrompt()) fragment.appendChild(createBaseCard())",
            javascript,
        )
        self.assertLess(
            javascript.index("fragment.appendChild(createBaseCard())"),
            javascript.index("rows.forEach((style) => fragment.appendChild(createCard(style)))"),
        )

    def test_generated_images_open_in_an_accessible_full_viewer(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        javascript = (ROOT / "assets" / "app.js").read_text(encoding="utf-8")
        stylesheet = (ROOT / "assets" / "app.css").read_text(encoding="utf-8")
        self.assertIn('id="image-viewer"', html)
        self.assertIn('id="close-image-viewer"', html)
        self.assertIn("function openImageViewer(image)", javascript)
        self.assertIn("image.addEventListener('click', () => openImageViewer(image))", javascript)
        self.assertIn("image.tabIndex = 0", javascript)
        self.assertIn(".image-viewer::backdrop", stylesheet)
        self.assertIn("cursor: zoom-in", stylesheet)


if __name__ == "__main__":
    unittest.main()
