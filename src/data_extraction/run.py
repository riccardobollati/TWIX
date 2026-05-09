"""Stage 1 — orchestrate sample → prompt → agent → save JSON.

Reads a PDF, samples first 5 pages, calls the agent with a schema-constrained
prompt, validates, retries on schema failures up to N times, saves to
results/<doc_name>__<model>.json.
"""

from __future__ import annotations

import json
import re
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .agent import CallResult, call_claude
from .prompt import build_prompt
from .sample_pdf import sample_first_pages
from ..eval.score import validate_tree


def _safe_doc_name(pdf_path: Path) -> str:
    return pdf_path.stem.replace("/", "_").replace(" ", "_")


def _read_json_loose(path: Path) -> Optional[dict]:
    """Parse JSON from a file, tolerating ```json fences if the agent left them."""
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8", errors="replace").strip()
    if not text:
        return None
    # Strip code fences if any.
    m = re.match(r"^```(?:json)?\s*\n([\s\S]*?)\n```\s*$", text)
    if m:
        text = m.group(1).strip()
    try:
        return json.loads(text)
    except Exception:
        # Try to find the first {...} JSON object.
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except Exception:
                return None
        return None


@dataclass
class StageOneResult:
    ok: bool
    status: str               # "ok" | "schema_fail" | "error"
    doc_name: str
    sample_pdf_path: str
    output_path: str | None
    tree: dict | None
    errors: list[str] = field(default_factory=list)
    calls: list[CallResult] = field(default_factory=list)


def run_stage1(
    pdf_path: str | Path,
    results_dir: str | Path,
    model: str = "claude-opus-4-7",
    model_short: str = "opus-4-7",
    project_root: str | Path | None = None,
    n_pages: int = 5,
    max_retries: int = 3,
) -> StageOneResult:
    pdf_path = Path(pdf_path).resolve()
    results_dir = Path(results_dir).resolve()
    results_dir.mkdir(parents=True, exist_ok=True)
    if project_root is None:
        project_root = Path.cwd()
    project_root = Path(project_root).resolve()

    doc_name = _safe_doc_name(pdf_path)
    sample_dir = project_root / ".tmp_pipeline" / "samples"
    sample_dir.mkdir(parents=True, exist_ok=True)
    sample_pdf = sample_dir / f"{doc_name}__sample.pdf"
    n_sampled = sample_first_pages(pdf_path, sample_pdf, n_pages=n_pages)

    output_path = results_dir / f"{doc_name}__{model_short}.json"
    if output_path.exists():
        output_path.unlink()

    calls: list[CallResult] = []
    errors_acc: list[str] = []
    last_errors: list[str] = []

    for attempt in range(1, max_retries + 1):
        prompt = build_prompt(
            doc_name=doc_name,
            model_id=model,
            n_sampled_pages=n_sampled,
            sample_pdf_path=str(sample_pdf),
            output_json_path=str(output_path),
            schema_errors_from_prior_attempt=last_errors if attempt > 1 else None,
        )
        result = call_claude(
            prompt=prompt,
            model=model,
            cwd=project_root,
            add_dirs=[str(project_root), str(sample_dir.parent), str(results_dir.parent)],
            timeout_s=1500,
        )
        calls.append(result)
        if not result.ok:
            errors_acc.append(f"attempt {attempt}: agent call failed: {result.stderr[:200]}")
            last_errors = ["the previous run errored before producing output; please retry"]
            continue

        tree = _read_json_loose(output_path)
        if tree is None:
            # Maybe the agent put it in stdout. Try parsing the result text.
            tree = _read_json_loose_from_text(result.text)
            if tree is not None:
                output_path.write_text(json.dumps(tree, indent=2, ensure_ascii=False), encoding="utf-8")
        if tree is None:
            errors_acc.append(f"attempt {attempt}: no JSON found at {output_path}")
            last_errors = [f"no JSON file found at {output_path}; you must Write the JSON to that exact path"]
            continue

        # Patch fixed metadata.
        tree.setdefault("doc_name", doc_name)
        tree.setdefault("model", model)
        tree.setdefault("sampled_pages", n_sampled)
        validation_errors = validate_tree(tree)
        if validation_errors:
            errors_acc.append(f"attempt {attempt}: schema errors: {validation_errors[:5]}")
            last_errors = validation_errors
            continue

        # Save and return.
        output_path.write_text(json.dumps(tree, indent=2, ensure_ascii=False), encoding="utf-8")
        return StageOneResult(
            ok=True,
            status="ok",
            doc_name=doc_name,
            sample_pdf_path=str(sample_pdf),
            output_path=str(output_path),
            tree=tree,
            errors=errors_acc,
            calls=calls,
        )

    return StageOneResult(
        ok=False,
        status="schema_fail" if last_errors else "error",
        doc_name=doc_name,
        sample_pdf_path=str(sample_pdf),
        output_path=str(output_path) if output_path.exists() else None,
        tree=None,
        errors=errors_acc,
        calls=calls,
    )


def _read_json_loose_from_text(text: str) -> Optional[dict]:
    text = (text or "").strip()
    if not text:
        return None
    m = re.search(r"```(?:json)?\s*\n([\s\S]*?)\n```", text)
    if m:
        text = m.group(1).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        return json.loads(text[start : end + 1])
    except Exception:
        return None
