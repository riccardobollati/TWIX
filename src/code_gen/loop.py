"""Stage 2 — iterative refinement loop.

code_gen.md §4: Author → write extractor → run on sample → score against gold
→ feedback. Save BEST candidate seen, not the last.
"""

from __future__ import annotations

import json
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from ..data_extraction.agent import CallResult
from ..eval.render import render
from ..eval.score import score, validate_tree
from .author import build_author_prompt, call_author
from .runner import run_extractor


@dataclass
class CodegenResult:
    status: str          # "passed" | "below_threshold" | "runtime_failure"
    threshold: float
    iterations_used: int
    max_iters: int
    best_iteration: int
    best_accuracy: float
    accuracy_history: list[float] = field(default_factory=list)
    history: list[dict] = field(default_factory=list)
    best_extractor_code: str | None = None
    best_candidate: dict | None = None
    best_eval_json: dict | None = None
    calls: list[CallResult] = field(default_factory=list)
    runtime_failure: bool = False
    # Aggregate token / latency counters across all Author calls in the loop.
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_latency_ms: int = 0


def _summary_for_iter(report: dict) -> str:
    if "runtime_error" in report:
        head = report["runtime_error"].splitlines()[0] if report["runtime_error"] else "runtime error"
        return f"runtime error: {head}"
    acc = report.get("accuracy", 0.0)
    nm = (report.get("components", {}) or {}).get("NodeMatchF1", {}) or {}
    cs = (report.get("components", {}) or {}).get("ContentScore", {}) or {}
    ss = (report.get("components", {}) or {}).get("StructureScore", {}) or {}
    return (
        f"acc={acc:.3f} nodeF1={nm.get('typed_f1', 0):.2f} "
        f"content={cs.get('overall', 0):.2f} struct={ss.get('edge_accuracy', 0):.2f}"
    )


def run_codegen_loop(
    gold: dict,
    sample_pdf_path: str | Path,
    extractor_path: str | Path,
    model: str = "claude-opus-4-7",
    project_root: str | Path | None = None,
    threshold: float = 0.9,
    max_iters: int = 25,
    early_stop_on_no_progress: bool = False,
    patience: int = 5,
    epsilon: float = 0.01,
    run_timeout_s: int = 60,
    progress_log = None,
) -> CodegenResult:
    sample_pdf_path = Path(sample_pdf_path).resolve()
    extractor_path = Path(extractor_path).resolve()
    extractor_path.parent.mkdir(parents=True, exist_ok=True)
    project_root = Path(project_root).resolve() if project_root else Path.cwd()

    history: list[dict] = []
    accuracy_history: list[float] = []
    best = {
        "accuracy": -1.0,
        "iter": -1,
        "code": None,
        "candidate": None,
        "report": None,
    }
    calls: list[CallResult] = []
    last_eval_json: Optional[dict] = None
    last_eval_txt: Optional[str] = None
    last_runtime_error: Optional[str] = None
    last_accuracy: Optional[float] = None
    current_extractor_code: Optional[str] = None
    no_progress_streak = 0
    runtime_failure_streak = 0

    for iteration in range(1, max_iters + 1):
        prompt = build_author_prompt(
            gold=gold,
            iteration=iteration,
            max_iters=max_iters,
            best_accuracy=best["accuracy"],
            current_accuracy=last_accuracy,
            threshold=threshold,
            sample_pdf_path=str(sample_pdf_path),
            extractor_path=str(extractor_path),
            current_extractor_code=current_extractor_code,
            last_eval_json=last_eval_json,
            last_eval_txt=last_eval_txt,
            last_runtime_error=last_runtime_error,
        )

        if progress_log is not None:
            progress_log(f"  iter {iteration}/{max_iters}: calling Author...")
        call = call_author(
            prompt=prompt,
            model=model,
            cwd=project_root,
            add_dirs=[str(project_root), str(extractor_path.parent), str(sample_pdf_path.parent)],
            timeout_s=1800,
        )
        calls.append(call)
        # Record per-iteration token usage and latency in history.
        iter_tokens_in = call.total_input
        iter_tokens_out = call.output_tokens
        iter_latency_ms = call.duration_ms

        if not call.ok:
            raw_subtype = call.raw.get("subtype") if call.raw else None
            raw_err = str(call.raw.get("error", ""))[:200] if call.raw else ""
            err = (
                f"author CLI call failed: subtype={raw_subtype} "
                f"err={raw_err} stderr={call.stderr[:300]}"
            )
            history.append({
                "iter": iteration, "accuracy": 0.0, "summary": err,
                "input_tokens": iter_tokens_in, "output_tokens": iter_tokens_out,
                "latency_ms": iter_latency_ms,
            })
            accuracy_history.append(0.0)
            last_accuracy = 0.0
            last_runtime_error = err
            last_eval_json = {"runtime_error": err, "accuracy": 0.0}
            last_eval_txt = None
            if progress_log is not None:
                progress_log(f"    -> author call failed (dur={call.duration_ms}ms): {err[:300]}")
            continue

        # Read the extractor code the author wrote.
        if not extractor_path.exists():
            err = f"author did not write {extractor_path}"
            history.append({
                "iter": iteration, "accuracy": 0.0, "summary": err,
                "input_tokens": iter_tokens_in, "output_tokens": iter_tokens_out,
                "latency_ms": iter_latency_ms,
            })
            accuracy_history.append(0.0)
            last_accuracy = 0.0
            last_runtime_error = err
            last_eval_json = {"runtime_error": err, "accuracy": 0.0}
            last_eval_txt = None
            if progress_log is not None:
                progress_log(f"    -> {err}")
            continue

        current_extractor_code = extractor_path.read_text(encoding="utf-8", errors="replace")

        # Run extractor.
        candidate, run_err = run_extractor(
            extractor_path=extractor_path,
            pdf_path=sample_pdf_path,
            timeout_s=run_timeout_s,
            cwd=project_root,
        )

        if run_err is not None:
            report = {"runtime_error": run_err, "accuracy": 0.0}
            last_runtime_error = run_err
            last_eval_json = report
            last_eval_txt = None
            last_accuracy = 0.0
            history.append({
                "iter": iteration,
                "accuracy": 0.0,
                "summary": _summary_for_iter(report),
                "runtime_error_head": run_err.splitlines()[0] if run_err else "",
                "input_tokens": iter_tokens_in,
                "output_tokens": iter_tokens_out,
                "latency_ms": iter_latency_ms,
            })
            accuracy_history.append(0.0)
            runtime_failure_streak += 1
            if progress_log is not None:
                progress_log(f"    -> runtime error: {(run_err.splitlines()[0] if run_err else '')[:120]}")
            if 0.0 > best["accuracy"]:
                best = {"accuracy": 0.0, "iter": iteration, "code": current_extractor_code,
                        "candidate": None, "report": report}
            continue

        runtime_failure_streak = 0
        # Validate against schema.
        schema_errors = validate_tree(candidate)
        if schema_errors:
            err_blob = "candidate output failed schema validation:\n  - " + "\n  - ".join(schema_errors[:10])
            report = {"runtime_error": err_blob, "accuracy": 0.0}
            last_runtime_error = err_blob
            last_eval_json = report
            last_eval_txt = None
            last_accuracy = 0.0
            history.append({
                "iter": iteration, "accuracy": 0.0,
                "summary": "schema-invalid output; treated as runtime error",
                "input_tokens": iter_tokens_in, "output_tokens": iter_tokens_out,
                "latency_ms": iter_latency_ms,
            })
            accuracy_history.append(0.0)
            if progress_log is not None:
                progress_log(f"    -> schema-invalid output (first error: {schema_errors[0][:120]})")
            if 0.0 > best["accuracy"]:
                best = {"accuracy": 0.0, "iter": iteration, "code": current_extractor_code,
                        "candidate": candidate, "report": report}
            continue

        # Score.
        report = score(gold=gold, candidate=candidate, reference="agent", threshold=threshold)
        eval_text = render(report, threshold=threshold)
        last_eval_json = report
        last_eval_txt = eval_text
        last_runtime_error = None
        last_accuracy = float(report.get("accuracy", 0.0))
        history.append({
            "iter": iteration,
            "accuracy": last_accuracy,
            "summary": _summary_for_iter(report),
            "input_tokens": iter_tokens_in,
            "output_tokens": iter_tokens_out,
            "latency_ms": iter_latency_ms,
        })
        accuracy_history.append(last_accuracy)
        if progress_log is not None:
            progress_log(f"    -> {_summary_for_iter(report)}")

        if last_accuracy > best["accuracy"]:
            best = {
                "accuracy": last_accuracy,
                "iter": iteration,
                "code": current_extractor_code,
                "candidate": candidate,
                "report": report,
            }
            no_progress_streak = 0
        else:
            no_progress_streak += 1

        if last_accuracy >= threshold:
            break

        if early_stop_on_no_progress:
            if no_progress_streak >= patience:
                break

    if best["accuracy"] < 0:
        best = {
            "accuracy": 0.0,
            "iter": history[-1]["iter"] if history else 0,
            "code": current_extractor_code,
            "candidate": None,
            "report": last_eval_json or {"runtime_error": "no candidate produced", "accuracy": 0.0},
        }

    if best["accuracy"] >= threshold:
        status = "passed"
    elif best["candidate"] is None:
        status = "runtime_failure"
    else:
        status = "below_threshold"

    total_input_tokens = sum(c.total_input for c in calls)
    total_output_tokens = sum(c.output_tokens for c in calls)
    total_latency_ms = sum(c.duration_ms for c in calls)

    return CodegenResult(
        status=status,
        threshold=threshold,
        iterations_used=len(history),
        max_iters=max_iters,
        best_iteration=int(best["iter"]),
        best_accuracy=float(best["accuracy"]),
        accuracy_history=accuracy_history,
        history=history,
        best_extractor_code=best["code"],
        best_candidate=best["candidate"],
        best_eval_json=best["report"],
        calls=calls,
        runtime_failure=(status == "runtime_failure"),
        total_input_tokens=total_input_tokens,
        total_output_tokens=total_output_tokens,
        total_latency_ms=total_latency_ms,
    )
