#!/usr/bin/env python3
"""Generate the Krea 2 comparison library through ComfyUI's HTTP API."""

from __future__ import annotations

import argparse
import copy
import hashlib
import io
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_STYLES = ROOT / "data" / "styles.json"
DEFAULT_BASE_PROMPTS = ROOT / "data" / "base_prompts.json"
DEFAULT_WORKFLOW = ROOT / "comfyui_workflows" / "Krea2_Basic_api.json"
DEFAULT_MANIFEST = ROOT / "data" / "generation_manifest.json"
DEFAULT_OUTPUT = ROOT / "images"
ID_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


class ConfigurationError(ValueError):
    """Raised when local generation inputs are invalid."""


@dataclass(frozen=True)
class WorkflowNodes:
    prompt: str
    sampler: str
    save_image: str
    resolution: str


@dataclass(frozen=True)
class GenerationJob:
    key: str
    style: dict[str, Any] | None
    base_prompt: dict[str, Any]
    full_prompt: str
    seed: int
    width: int
    height: int
    output_path: Path
    relative_output_path: str
    prompt_sha256: str

    @property
    def output_id(self) -> str:
        return self.style["id"] if self.style is not None else "base"

    @property
    def display_name(self) -> str:
        return self.style["name"] if self.style is not None else "Base image (no style)"


@dataclass
class ActiveJob:
    job: GenerationJob
    queued_at: float
    poll_errors: int = 0


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def resolve_path(value: str | Path) -> Path:
    path = Path(value)
    return path.resolve() if path.is_absolute() else (ROOT / path).resolve()


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise ConfigurationError(f"File not found: {path}") from error
    except json.JSONDecodeError as error:
        raise ConfigurationError(f"Invalid JSON in {path}: {error}") from error


def atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".part")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_id(value: Any, label: str) -> str:
    if not isinstance(value, str) or not ID_PATTERN.fullmatch(value):
        raise ConfigurationError(
            f"{label} must use lowercase letters, numbers, and single hyphens: {value!r}"
        )
    return value


def load_styles(path: Path) -> list[dict[str, Any]]:
    payload = read_json(path)
    records = payload.get("styles") if isinstance(payload, dict) else None
    if not isinstance(records, list) or not records:
        raise ConfigurationError(f"{path} must contain a non-empty 'styles' array")

    ids: set[str] = set()
    orders: set[int] = set()
    descriptors: set[str] = set()
    for index, record in enumerate(records, start=1):
        if not isinstance(record, dict):
            raise ConfigurationError(f"Style {index} must be an object")
        style_id = validate_id(record.get("id"), f"Style {index} id")
        if style_id in ids:
            raise ConfigurationError(f"Duplicate style id: {style_id}")
        ids.add(style_id)

        order = record.get("order")
        if not isinstance(order, int) or order < 1 or order in orders:
            raise ConfigurationError(f"Invalid or duplicate order for {style_id}: {order!r}")
        orders.add(order)

        name = record.get("name")
        descriptor = record.get("descriptor")
        categories = record.get("categories")
        if not isinstance(name, str) or not name.strip():
            raise ConfigurationError(f"Missing name for {style_id}")
        if not isinstance(descriptor, str) or not descriptor.strip():
            raise ConfigurationError(f"Missing descriptor for {style_id}")
        normalized_descriptor = " ".join(descriptor.split()).casefold()
        if normalized_descriptor in descriptors:
            raise ConfigurationError(f"Duplicate descriptor found at {style_id}")
        descriptors.add(normalized_descriptor)
        if (
            not isinstance(categories, list)
            or not categories
            or any(not isinstance(category, str) or not category.strip() for category in categories)
        ):
            raise ConfigurationError(f"Invalid categories for {style_id}")

    return sorted(records, key=lambda record: record["order"])


def load_base_prompt_config(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    payload = read_json(path)
    if not isinstance(payload, dict):
        raise ConfigurationError(f"{path} must contain a JSON object")

    template = payload.get("prompt_template")
    if not isinstance(template, str) or not template.strip():
        raise ConfigurationError("base_prompts.json requires a non-empty prompt_template")
    try:
        template.format(base_prompt="base", style_descriptor="style", style_name="name")
    except (KeyError, ValueError) as error:
        raise ConfigurationError(f"Invalid prompt_template: {error}") from error

    prompt_records = payload.get("prompts")
    if not isinstance(prompt_records, list):
        raise ConfigurationError("base_prompts.json requires a 'prompts' array")

    enabled: list[dict[str, Any]] = []
    ids: set[str] = set()
    for index, prompt in enumerate(prompt_records, start=1):
        if not isinstance(prompt, dict):
            raise ConfigurationError(f"Base prompt {index} must be an object")
        prompt_id = validate_id(prompt.get("id"), f"Base prompt {index} id")
        if prompt_id in ids:
            raise ConfigurationError(f"Duplicate base prompt id: {prompt_id}")
        ids.add(prompt_id)
        if not isinstance(prompt.get("label"), str) or not prompt["label"].strip():
            raise ConfigurationError(f"Missing label for base prompt {prompt_id}")
        if not isinstance(prompt.get("prompt"), str) or not prompt["prompt"].strip():
            raise ConfigurationError(f"Missing prompt text for base prompt {prompt_id}")
        seed = prompt.get("seed")
        if not isinstance(seed, int) or isinstance(seed, bool) or seed < 0:
            raise ConfigurationError(f"Seed for {prompt_id} must be a non-negative integer")
        width, height = prompt.get("width"), prompt.get("height")
        if (width is None) != (height is None):
            raise ConfigurationError(
                f"Base prompt {prompt_id} must define both width and height, or neither"
            )
        for dimension_name, dimension in (("width", width), ("height", height)):
            if dimension is not None and (
                not isinstance(dimension, int) or isinstance(dimension, bool) or dimension < 1
            ):
                raise ConfigurationError(
                    f"{dimension_name} for {prompt_id} must be a positive integer"
                )
        if prompt.get("enabled", True):
            enabled.append(prompt)

    return payload, enabled


def select_records(
    records: list[dict[str, Any]], requested: list[str] | None, record_type: str
) -> list[dict[str, Any]]:
    if not requested:
        return records
    lookup: dict[str, dict[str, Any]] = {}
    for record in records:
        lookup[record["id"].casefold()] = record
        lookup[record["name" if record_type == "style" else "label"].casefold()] = record
    selected: list[dict[str, Any]] = []
    missing: list[str] = []
    seen: set[str] = set()
    for value in requested:
        record = lookup.get(value.casefold())
        if record is None:
            missing.append(value)
        elif record["id"] not in seen:
            selected.append(record)
            seen.add(record["id"])
    if missing:
        raise ConfigurationError(f"Unknown {record_type} selection(s): {', '.join(missing)}")
    return selected


def compose_prompt(template: str, base_prompt: dict[str, Any], style: dict[str, Any]) -> str:
    return template.format(
        base_prompt=base_prompt["prompt"].strip(),
        style_descriptor=style["descriptor"].strip(),
        style_name=style["name"].strip(),
    ).strip()


def find_workflow_node(
    workflow: dict[str, Any],
    class_type: str,
    explicit_id: str | None = None,
    preferred_title: str | None = None,
) -> str:
    if explicit_id is not None:
        node = workflow.get(str(explicit_id))
        if not isinstance(node, dict) or node.get("class_type") != class_type:
            raise ConfigurationError(
                f"Workflow node {explicit_id} is not a {class_type} node"
            )
        return str(explicit_id)

    candidates = [
        (node_id, node)
        for node_id, node in workflow.items()
        if isinstance(node, dict) and node.get("class_type") == class_type
    ]
    if preferred_title:
        preferred = [
            node_id
            for node_id, node in candidates
            if preferred_title.casefold()
            in str(node.get("_meta", {}).get("title", "")).casefold()
        ]
        if len(preferred) == 1:
            return preferred[0]
    if len(candidates) == 1:
        return candidates[0][0]
    ids = ", ".join(node_id for node_id, _ in candidates) or "none"
    raise ConfigurationError(
        f"Could not uniquely select {class_type}; candidates: {ids}. Use a node-id option."
    )


def discover_workflow_nodes(workflow: dict[str, Any], args: argparse.Namespace) -> WorkflowNodes:
    return WorkflowNodes(
        prompt=find_workflow_node(
            workflow, "CLIPTextEncode", args.prompt_node_id, preferred_title="positive"
        ),
        sampler=find_workflow_node(workflow, "KSampler", args.sampler_node_id),
        save_image=find_workflow_node(workflow, "SaveImage", args.save_node_id),
        resolution=find_workflow_node(
            workflow, "ResolutionMaster", args.resolution_node_id
        ),
    )


def workflow_resolution(workflow: dict[str, Any]) -> tuple[int, int] | None:
    candidates = [
        node
        for node in workflow.values()
        if isinstance(node, dict) and node.get("class_type") == "ResolutionMaster"
    ]
    if len(candidates) != 1:
        return None
    inputs = candidates[0].get("inputs", {})
    width, height = inputs.get("width"), inputs.get("height")
    return (width, height) if isinstance(width, int) and isinstance(height, int) else None


def set_workflow_seed(workflow: dict[str, Any], sampler_id: str, seed: int) -> None:
    sampler_inputs = workflow[sampler_id].setdefault("inputs", {})
    seed_input = sampler_inputs.get("seed")
    if (
        isinstance(seed_input, list)
        and seed_input
        and str(seed_input[0]) in workflow
        and isinstance(workflow[str(seed_input[0])], dict)
        and "seed" in workflow[str(seed_input[0])].get("inputs", {})
    ):
        workflow[str(seed_input[0])]["inputs"]["seed"] = seed
    else:
        sampler_inputs["seed"] = seed


def prepare_workflow(
    original: dict[str, Any], nodes: WorkflowNodes, job: GenerationJob
) -> dict[str, Any]:
    workflow = copy.deepcopy(original)
    workflow[nodes.prompt].setdefault("inputs", {})["text"] = job.full_prompt
    set_workflow_seed(workflow, nodes.sampler, job.seed)
    resolution_inputs = workflow[nodes.resolution].setdefault("inputs", {})
    resolution_inputs["width"] = job.width
    resolution_inputs["height"] = job.height
    workflow[nodes.save_image].setdefault("inputs", {})["filename_prefix"] = (
        f"krea2-style-library/{job.base_prompt['id']}/{job.output_id}"
    )
    return workflow


def create_jobs(
    styles: list[dict[str, Any]],
    base_prompts: list[dict[str, Any]],
    template: str,
    output_dir: Path,
    image_format: str = "png",
    default_resolution: tuple[int, int] | None = None,
) -> list[GenerationJob]:
    try:
        output_dir.relative_to(ROOT)
    except ValueError as error:
        raise ConfigurationError("The output directory must be inside the project") from error

    jobs: list[GenerationJob] = []
    for base_prompt in base_prompts:
        width, height = base_prompt.get("width"), base_prompt.get("height")
        if width is None or height is None:
            if default_resolution is None:
                raise ConfigurationError(
                    f"Base prompt {base_prompt['id']} has no dimensions and the workflow resolution is unavailable"
                )
            width, height = default_resolution

        base_text = base_prompt["prompt"].strip()
        base_output_path = output_dir / base_prompt["id"] / f"base.{image_format}"
        jobs.append(
            GenerationJob(
                key=f"{base_prompt['id']}/base",
                style=None,
                base_prompt=base_prompt,
                full_prompt=base_text,
                seed=base_prompt["seed"],
                width=width,
                height=height,
                output_path=base_output_path,
                relative_output_path=base_output_path.relative_to(ROOT).as_posix(),
                prompt_sha256=sha256_text(base_text),
            )
        )
        for style in styles:
            full_prompt = compose_prompt(template, base_prompt, style)
            output_path = output_dir / base_prompt["id"] / f"{style['id']}.{image_format}"
            jobs.append(
                GenerationJob(
                    key=f"{base_prompt['id']}/{style['id']}",
                    style=style,
                    base_prompt=base_prompt,
                    full_prompt=full_prompt,
                    seed=base_prompt["seed"],
                    width=width,
                    height=height,
                    output_path=output_path,
                    relative_output_path=output_path.relative_to(ROOT).as_posix(),
                    prompt_sha256=sha256_text(full_prompt),
                )
            )
    return jobs


class ComfyClient:
    def __init__(self, base_url: str, timeout: float = 30.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.client_id = str(uuid.uuid4())

    def _request(self, method: str, path: str, payload: Any = None) -> bytes:
        data = None
        headers: dict[str, str] = {}
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        url = f"{self.base_url}{path}"
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return response.read()
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"HTTP {error.code} from {url}: {detail}") from error
        except urllib.error.URLError as error:
            raise RuntimeError(
                f"Could not connect to ComfyUI at {self.base_url}: {error.reason}"
            ) from error

    def json_request(self, method: str, path: str, payload: Any = None) -> Any:
        raw = self._request(method, path, payload)
        return json.loads(raw.decode("utf-8")) if raw else {}

    def check_server(self) -> None:
        self.json_request("GET", "/system_stats")

    def queue(self, workflow: dict[str, Any]) -> str:
        result = self.json_request(
            "POST", "/prompt", {"prompt": workflow, "client_id": self.client_id}
        )
        prompt_id = result.get("prompt_id") if isinstance(result, dict) else None
        if not prompt_id:
            raise RuntimeError(f"ComfyUI did not return a prompt_id: {result}")
        return str(prompt_id)

    def history(self, prompt_id: str) -> dict[str, Any] | None:
        result = self.json_request("GET", f"/history/{urllib.parse.quote(prompt_id)}")
        if not isinstance(result, dict):
            return None
        entry = result.get(prompt_id)
        return entry if isinstance(entry, dict) else None

    def download_output(self, image: dict[str, Any]) -> bytes:
        query = urllib.parse.urlencode(
            {
                "filename": image.get("filename", ""),
                "subfolder": image.get("subfolder", ""),
                "type": image.get("type", "output"),
            }
        )
        return self._request("GET", f"/view?{query}")


def load_manifest(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"schema_version": 1, "workflow_sha256": None, "updated_at": None, "images": {}}
    payload = read_json(path)
    if not isinstance(payload, dict) or not isinstance(payload.get("images"), dict):
        raise ConfigurationError(f"Invalid generation manifest: {path}")
    return payload


def save_manifest(path: Path, manifest: dict[str, Any]) -> None:
    manifest["updated_at"] = utc_now()
    atomic_write_json(path, manifest)


def manifest_record(job: GenerationJob, workflow_hash: str, status: str) -> dict[str, Any]:
    return {
        "base_prompt_id": job.base_prompt["id"],
        "style_id": job.style["id"] if job.style is not None else None,
        "kind": "style" if job.style is not None else "base",
        "status": status,
        "path": job.relative_output_path,
        "seed": job.seed,
        "width": job.width,
        "height": job.height,
        "prompt_sha256": job.prompt_sha256,
        "workflow_sha256": workflow_hash,
    }


def save_comfy_png(data: bytes, destination: Path) -> None:
    """Store ComfyUI's PNG response without re-encoding or stripping metadata."""
    if not data.startswith(PNG_SIGNATURE):
        raise RuntimeError("ComfyUI returned an output that is not a PNG file")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".part")
    temporary.write_bytes(data)
    if temporary.stat().st_size == 0:
        raise RuntimeError(f"Generated an empty image: {temporary}")
    temporary.replace(destination)


def validate_webp_support() -> None:
    try:
        from PIL import Image  # noqa: F401
    except ImportError as error:
        raise ConfigurationError(
            "WebP output requires Pillow. Run: python -m pip install -r requirements.txt"
        ) from error


def save_webp(data: bytes, destination: Path, quality: int) -> None:
    """Convert ComfyUI's PNG response to WebP; PNG metadata is not retained."""
    if not data.startswith(PNG_SIGNATURE):
        raise RuntimeError("ComfyUI returned an output that is not a PNG file")
    from PIL import Image

    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".part")
    with Image.open(io.BytesIO(data)) as image:
        image.save(temporary, format="WEBP", quality=quality, method=6)
    if temporary.stat().st_size == 0:
        raise RuntimeError(f"Generated an empty image: {temporary}")
    temporary.replace(destination)


def save_output(data: bytes, destination: Path, image_format: str, webp_quality: int) -> None:
    if image_format == "webp":
        save_webp(data, destination, webp_quality)
    else:
        save_comfy_png(data, destination)


def history_error(entry: dict[str, Any]) -> str | None:
    status = entry.get("status")
    if not isinstance(status, dict):
        return None
    if str(status.get("status_str", "")).casefold() != "error":
        return None
    messages = status.get("messages")
    return json.dumps(messages, ensure_ascii=False) if messages else "ComfyUI reported an error"


def completed_output(entry: dict[str, Any], save_node_id: str) -> dict[str, Any] | None:
    outputs = entry.get("outputs")
    if not isinstance(outputs, dict):
        return None
    node_output = outputs.get(save_node_id)
    if not isinstance(node_output, dict):
        return None
    images = node_output.get("images")
    if not isinstance(images, list) or not images or not isinstance(images[0], dict):
        return None
    return images[0]


def is_history_complete(entry: dict[str, Any]) -> bool:
    status = entry.get("status")
    return bool(isinstance(status, dict) and status.get("completed")) or bool(entry.get("outputs"))


def output_exists(job: GenerationJob) -> bool:
    return job.output_path.is_file() and job.output_path.stat().st_size > 0


def pending_jobs(
    jobs: list[GenerationJob], overwrite: bool = False
) -> tuple[list[GenerationJob], list[GenerationJob]]:
    if overwrite:
        return list(jobs), []
    pending: list[GenerationJob] = []
    existing: list[GenerationJob] = []
    for job in jobs:
        (existing if output_exists(job) else pending).append(job)
    return pending, existing


def print_job_summary(
    jobs: list[GenerationJob], styles: int, prompts: int, overwrite: bool = False
) -> None:
    remaining, existing = pending_jobs(jobs, overwrite)
    print(f"Styles in selection: {styles}")
    print(f"Base prompts in selection: {prompts}")
    print(f"Outputs in selection: {len(jobs)}")
    print(f"Existing outputs to skip: {len(existing)}")
    print(f"Outputs to generate: {len(remaining)}")
    if remaining:
        print("Next outputs:")
    for job in remaining[:10]:
        print(
            f"  {job.base_prompt['id']} / {job.display_name} -> {job.relative_output_path} "
            f"({job.width}x{job.height}, seed {job.seed})"
        )
    if len(remaining) > 10:
        print(f"  ...and {len(remaining) - 10} more")


def execute_jobs(
    jobs: list[GenerationJob],
    workflow: dict[str, Any],
    nodes: WorkflowNodes,
    workflow_hash: str,
    manifest: dict[str, Any],
    manifest_path: Path,
    client: ComfyClient,
    args: argparse.Namespace,
    image_format: str,
    webp_quality: int,
) -> tuple[int, int, int]:
    pending: deque[GenerationJob] = deque()
    skipped = 0
    for job in jobs:
        if output_exists(job) and not args.overwrite:
            current = manifest_record(job, workflow_hash, "complete")
            previous = manifest["images"].get(job.key)
            if (
                isinstance(previous, dict)
                and previous.get("path") == job.relative_output_path
            ):
                record = {**current, **previous}
                record["status"] = "complete"
                record["path"] = job.relative_output_path
                record.setdefault("width", job.width)
                record.setdefault("height", job.height)
            else:
                record = current
            record["bytes"] = job.output_path.stat().st_size
            record["recovered_at"] = utc_now()
            manifest["images"][job.key] = record
            skipped += 1
        else:
            pending.append(job)
    manifest["workflow_sha256"] = workflow_hash
    save_manifest(manifest_path, manifest)

    if not pending:
        return 0, 0, skipped

    client.check_server()
    print(f"Connected to ComfyUI at {client.base_url}")

    active: dict[str, ActiveJob] = {}
    completed = 0
    failed = 0
    total_to_run = len(pending)

    while pending or active:
        while pending and len(active) < args.max_in_flight:
            job = pending.popleft()
            try:
                prompt_id = client.queue(prepare_workflow(workflow, nodes, job))
            except Exception as error:
                record = manifest_record(job, workflow_hash, "failed")
                record.update({"failed_at": utc_now(), "error": str(error)})
                manifest["images"][job.key] = record
                save_manifest(manifest_path, manifest)
                failed += 1
                print(f"FAILED TO QUEUE {job.key}: {error}", file=sys.stderr)
                continue

            record = manifest_record(job, workflow_hash, "queued")
            record.update({"prompt_id": prompt_id, "queued_at": utc_now()})
            manifest["images"][job.key] = record
            save_manifest(manifest_path, manifest)
            active[prompt_id] = ActiveJob(job=job, queued_at=time.monotonic())
            print(f"Queued {job.key} [{completed + failed + len(active)}/{total_to_run}]")

        made_progress = False
        for prompt_id, active_job in list(active.items()):
            job = active_job.job
            if time.monotonic() - active_job.queued_at > args.job_timeout:
                record = manifest_record(job, workflow_hash, "failed")
                record.update(
                    {
                        "prompt_id": prompt_id,
                        "failed_at": utc_now(),
                        "error": f"Timed out after {args.job_timeout:g} seconds",
                    }
                )
                manifest["images"][job.key] = record
                save_manifest(manifest_path, manifest)
                del active[prompt_id]
                failed += 1
                made_progress = True
                print(f"TIMED OUT {job.key}", file=sys.stderr)
                continue

            try:
                entry = client.history(prompt_id)
            except RuntimeError as error:
                active_job.poll_errors += 1
                if active_job.poll_errors >= 5:
                    record = manifest_record(job, workflow_hash, "failed")
                    record.update(
                        {"prompt_id": prompt_id, "failed_at": utc_now(), "error": str(error)}
                    )
                    manifest["images"][job.key] = record
                    save_manifest(manifest_path, manifest)
                    del active[prompt_id]
                    failed += 1
                    made_progress = True
                    print(f"FAILED {job.key}: {error}", file=sys.stderr)
                continue

            if entry is None or not is_history_complete(entry):
                continue

            error_message = history_error(entry)
            image = completed_output(entry, nodes.save_image)
            if error_message or image is None:
                record = manifest_record(job, workflow_hash, "failed")
                record.update(
                    {
                        "prompt_id": prompt_id,
                        "failed_at": utc_now(),
                        "error": error_message or "SaveImage returned no image",
                    }
                )
                manifest["images"][job.key] = record
                failed += 1
                print(f"FAILED {job.key}: {record['error']}", file=sys.stderr)
            else:
                try:
                    image_bytes = client.download_output(image)
                    save_output(image_bytes, job.output_path, image_format, webp_quality)
                    record = manifest_record(job, workflow_hash, "complete")
                    record.update(
                        {
                            "prompt_id": prompt_id,
                            "generated_at": utc_now(),
                            "bytes": job.output_path.stat().st_size,
                            "comfy_output": {
                                "filename": image.get("filename"),
                                "subfolder": image.get("subfolder", ""),
                                "type": image.get("type", "output"),
                            },
                        }
                    )
                    manifest["images"][job.key] = record
                    completed += 1
                    print(f"Saved {job.relative_output_path}")
                except Exception as error:
                    record = manifest_record(job, workflow_hash, "failed")
                    record.update(
                        {"prompt_id": prompt_id, "failed_at": utc_now(), "error": str(error)}
                    )
                    manifest["images"][job.key] = record
                    failed += 1
                    print(f"FAILED {job.key}: {error}", file=sys.stderr)

            save_manifest(manifest_path, manifest)
            del active[prompt_id]
            made_progress = True

        if active and not made_progress:
            time.sleep(min(args.poll_interval, 60.0))

    return completed, failed, skipped


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--comfy-url", default="http://127.0.0.1:8188")
    parser.add_argument("--workflow", default=str(DEFAULT_WORKFLOW))
    parser.add_argument("--styles-file", default=str(DEFAULT_STYLES))
    parser.add_argument("--base-prompts-file", default=str(DEFAULT_BASE_PROMPTS))
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--style", action="append", help="Style id or exact name; repeatable")
    parser.add_argument(
        "--base-prompt", action="append", help="Base-prompt id or exact label; repeatable"
    )
    parser.add_argument("--limit", type=int, help="Limit the final job list for a pilot run")
    parser.add_argument("--max-in-flight", type=int, default=2)
    parser.add_argument("--poll-interval", type=float, default=2.0)
    parser.add_argument("--job-timeout", type=float, default=3600.0)
    parser.add_argument("--request-timeout", type=float, default=30.0)
    parser.add_argument(
        "--image-format",
        choices=("png", "webp"),
        default="png",
        help="Output format. PNG is the default and preserves ComfyUI metadata.",
    )
    parser.add_argument(
        "--webp-quality",
        type=int,
        default=88,
        help="WebP quality from 1 to 100; used only with --image-format webp.",
    )
    parser.add_argument("--prompt-node-id")
    parser.add_argument("--sampler-node-id")
    parser.add_argument("--save-node-id")
    parser.add_argument("--resolution-node-id")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser


def run(args: argparse.Namespace) -> int:
    if args.limit is not None and args.limit < 1:
        raise ConfigurationError("--limit must be at least 1")
    if args.max_in_flight < 1:
        raise ConfigurationError("--max-in-flight must be at least 1")
    if args.poll_interval <= 0 or args.job_timeout <= 0 or args.request_timeout <= 0:
        raise ConfigurationError("Timeout and polling values must be positive")
    if not 1 <= args.webp_quality <= 100:
        raise ConfigurationError("--webp-quality must be from 1 to 100")

    styles_path = resolve_path(args.styles_file)
    prompt_config_path = resolve_path(args.base_prompts_file)
    workflow_path = resolve_path(args.workflow)
    manifest_path = resolve_path(args.manifest)
    output_dir = resolve_path(args.output_dir)

    styles = select_records(load_styles(styles_path), args.style, "style")
    prompt_config, enabled_prompts = load_base_prompt_config(prompt_config_path)
    if not enabled_prompts:
        raise ConfigurationError(
            f"No enabled base prompts are configured in {prompt_config_path}. See README.md."
        )
    base_prompts = select_records(enabled_prompts, args.base_prompt, "base prompt")

    workflow = read_json(workflow_path)
    if not isinstance(workflow, dict):
        raise ConfigurationError("The ComfyUI API workflow must be a JSON object")
    nodes = discover_workflow_nodes(workflow, args)
    default_resolution = workflow_resolution(workflow)
    workflow_hash = sha256_file(workflow_path)
    jobs = create_jobs(
        styles,
        base_prompts,
        prompt_config["prompt_template"],
        output_dir,
        args.image_format,
        default_resolution,
    )
    if args.limit is not None:
        jobs = jobs[: args.limit]

    print(f"Workflow: {workflow_path}")
    print(
        f"Nodes: prompt={nodes.prompt}, sampler={nodes.sampler}, "
        f"resolution={nodes.resolution}, save={nodes.save_image}"
    )
    print(
        f"Workflow default resolution: {default_resolution[0]}x{default_resolution[1]}"
        if default_resolution
        else "Workflow default resolution: unknown"
    )
    if args.image_format == "webp":
        print(f"Output: WebP quality {args.webp_quality}")
        print("Warning: WebP conversion does not retain ComfyUI PNG metadata.")
    else:
        print("Output: PNG (original ComfyUI bytes; embedded metadata preserved)")
    print_job_summary(
        jobs,
        len({job.style["id"] for job in jobs if job.style is not None}),
        len({job.base_prompt["id"] for job in jobs}),
        args.overwrite,
    )

    if args.dry_run:
        print("Dry run complete; nothing was queued or written.")
        return 0

    if args.image_format == "webp":
        validate_webp_support()
    manifest = load_manifest(manifest_path)
    client = ComfyClient(args.comfy_url, timeout=args.request_timeout)
    completed, failed, skipped = execute_jobs(
        jobs,
        workflow,
        nodes,
        workflow_hash,
        manifest,
        manifest_path,
        client,
        args,
        args.image_format,
        args.webp_quality,
    )
    print()
    print(f"Complete: {completed} | Skipped: {skipped} | Failed: {failed}")
    return 1 if failed else 0


def main() -> None:
    parser = build_parser()
    try:
        raise SystemExit(run(parser.parse_args()))
    except ConfigurationError as error:
        print(f"Configuration error: {error}", file=sys.stderr)
        raise SystemExit(2) from error
    except KeyboardInterrupt:
        print("\nInterrupted. Completed outputs and manifest state were preserved.", file=sys.stderr)
        raise SystemExit(130)


if __name__ == "__main__":
    main()
