"""Top-level orchestrator: stage1, stage2, stage3, all, all-samples.

Usage:
    python src/run_pipeline.py stage1       <pdf_path>
    python src/run_pipeline.py stage2       <pdf_path>
    python src/run_pipeline.py stage3       <pdf_path>
    python src/run_pipeline.py all          <pdf_path>
    python src/run_pipeline.py all-samples
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import sys
import time
from dataclasses import asdict
from pathlib import Path
from typing import Optional

# Make this script runnable without `python -m`.
HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.code_gen.loop import CodegenResult, run_codegen_loop
from src.data_extraction.run import StageOneResult, run_stage1
from src.data_extraction.sample_pdf import sample_first_pages
from src.eval.render import render
from src.eval.score import score


MODEL = "claude-opus-4-7"
MODEL_SHORT = "opus-4-7"

SAMPLE_DIR = ROOT / "data" / "sample_data"
RESULTS_DIR = ROOT / "results"
TMP_DIR = ROOT / ".tmp_pipeline"

THRESHOLD = 0.9
MAX_ITERS = 25
RUN_TIMEOUT_S = 60


def _safe_doc_name(pdf_path: Path) -> str:
    return pdf_path.stem.replace("/", "_").replace(" ", "_")


def _now_utc_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _now_utc_stamp() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%d_%H%M%S")


def _result_paths(doc_name: str) -> dict:
    return {
        "gold_json":    str(RESULTS_DIR / f"{doc_name}__{MODEL_SHORT}.json"),
        "extractor_py": str(RESULTS_DIR / f"{doc_name}__{MODEL_SHORT}.extractor.py"),
        "code_output":  str(RESULTS_DIR / f"{doc_name}__{MODEL_SHORT}.code_output.json"),
        "eval_json":    str(RESULTS_DIR / f"{doc_name}__{MODEL_SHORT}.eval.json"),
        "eval_txt":     str(RESULTS_DIR / f"{doc_name}__{MODEL_SHORT}.eval.txt"),
        "codegen_log":  str(RESULTS_DIR / f"{doc_name}__{MODEL_SHORT}.codegen_log.json"),
        "stage1_log":   str(RESULTS_DIR / f"{doc_name}__{MODEL_SHORT}.stage1_log.json"),
    }


def _ensure_dirs():
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    (TMP_DIR / "samples").mkdir(parents=True, exist_ok=True)


def _print(msg: str):
    print(msg, flush=True)


# --------------------------------------------------------------------------- #
# Stage 1
# --------------------------------------------------------------------------- #

def stage1(pdf_path: Path) -> tuple[StageOneResult, list[dict]]:
    _ensure_dirs()
    doc_name = _safe_doc_name(pdf_path)
    paths = _result_paths(doc_name)
    _print(f"[stage1] {doc_name}")
    res = run_stage1(
        pdf_path=pdf_path,
        results_dir=RESULTS_DIR,
        model=MODEL,
        model_short=MODEL_SHORT,
        project_root=ROOT,
        n_pages=5,
        max_retries=3,
    )
    call_logs = []
    for c in res.calls:
        call_logs.append({
            "ok": c.ok,
            "duration_ms": c.duration_ms,
            "input_tokens": c.input_tokens,
            "output_tokens": c.output_tokens,
            "cache_read": c.cache_read,
            "cache_creation": c.cache_creation,
        })
    log = {
        "doc_name": doc_name,
        "stage": "stage1",
        "model": MODEL,
        "status": res.status,
        "ok": res.ok,
        "errors": res.errors,
        "output_path": res.output_path,
        "calls": call_logs,
    }
    Path(paths["stage1_log"]).write_text(json.dumps(log, indent=2, ensure_ascii=False), encoding="utf-8")
    if res.ok:
        _print(f"  stage1 ok -> {res.output_path}")
    else:
        _print(f"  stage1 FAILED ({res.status}); errors[0]: {res.errors[0] if res.errors else '?'}")
    return res, call_logs


# --------------------------------------------------------------------------- #
# Stage 2
# --------------------------------------------------------------------------- #

def stage2(pdf_path: Path) -> tuple[Optional[CodegenResult], list[dict]]:
    _ensure_dirs()
    doc_name = _safe_doc_name(pdf_path)
    paths = _result_paths(doc_name)
    gold_path = Path(paths["gold_json"])
    if not gold_path.exists():
        _print(f"[stage2] {doc_name}: gold JSON missing at {gold_path}, run stage1 first")
        return None, []
    gold = json.loads(gold_path.read_text(encoding="utf-8"))
    sample_pdf = TMP_DIR / "samples" / f"{doc_name}__sample.pdf"
    if not sample_pdf.exists():
        sample_first_pages(pdf_path, sample_pdf, n_pages=5)
    extractor_path = Path(paths["extractor_py"])
    _print(f"[stage2] {doc_name} (max_iters={MAX_ITERS}, threshold={THRESHOLD})")

    def progress(msg: str):
        _print(msg)

    res = run_codegen_loop(
        gold=gold,
        sample_pdf_path=sample_pdf,
        extractor_path=extractor_path,
        model=MODEL,
        project_root=ROOT,
        threshold=THRESHOLD,
        max_iters=MAX_ITERS,
        early_stop_on_no_progress=False,
        run_timeout_s=RUN_TIMEOUT_S,
        progress_log=progress,
    )
    call_logs = []
    for c in res.calls:
        call_logs.append({
            "ok": c.ok,
            "duration_ms": c.duration_ms,
            "input_tokens": c.input_tokens,
            "output_tokens": c.output_tokens,
            "cache_read": c.cache_read,
            "cache_creation": c.cache_creation,
        })

    # Save BEST extractor + outputs.
    if res.best_extractor_code:
        Path(paths["extractor_py"]).write_text(res.best_extractor_code, encoding="utf-8")
    if res.best_candidate is not None:
        Path(paths["code_output"]).write_text(
            json.dumps(res.best_candidate, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    if res.best_eval_json is not None:
        # Make sure the eval.json reflects the BEST candidate; also re-render eval.txt.
        Path(paths["eval_json"]).write_text(
            json.dumps(res.best_eval_json, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        try:
            txt = render(res.best_eval_json, threshold=THRESHOLD)
        except Exception as e:
            txt = f"(render failed: {e})\n"
        Path(paths["eval_txt"]).write_text(txt, encoding="utf-8")

    log = {
        "doc_name": doc_name,
        "model": MODEL,
        "status": res.status,
        "threshold": res.threshold,
        "iterations_used": res.iterations_used,
        "max_iters": res.max_iters,
        "best_iteration": res.best_iteration,
        "best_accuracy": res.best_accuracy,
        "accuracy_history": res.accuracy_history,
        "history": res.history,
        "calls": call_logs,
    }
    Path(paths["codegen_log"]).write_text(json.dumps(log, indent=2, ensure_ascii=False), encoding="utf-8")
    _print(f"  stage2 -> status={res.status}, best_iter={res.best_iteration}, best_acc={res.best_accuracy:.4f}")
    return res, call_logs


# --------------------------------------------------------------------------- #
# Stage 3
# --------------------------------------------------------------------------- #

def stage3(pdf_path: Path) -> Optional[dict]:
    _ensure_dirs()
    doc_name = _safe_doc_name(pdf_path)
    paths = _result_paths(doc_name)
    gold_path = Path(paths["gold_json"])
    cand_path = Path(paths["code_output"])
    if not gold_path.exists() or not cand_path.exists():
        _print(f"[stage3] {doc_name}: missing gold or code_output; skipping")
        return None
    gold = json.loads(gold_path.read_text(encoding="utf-8"))
    cand = json.loads(cand_path.read_text(encoding="utf-8"))
    report = score(gold=gold, candidate=cand, reference="agent", threshold=THRESHOLD)
    Path(paths["eval_json"]).write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    Path(paths["eval_txt"]).write_text(render(report, threshold=THRESHOLD), encoding="utf-8")
    _print(f"[stage3] {doc_name}: accuracy={report['accuracy']:.4f}")
    return report


# --------------------------------------------------------------------------- #
# All / all-samples
# --------------------------------------------------------------------------- #

def run_all(pdf_path: Path, session_state: dict | None = None) -> dict:
    """Run stage1 + stage2 + stage3 for one PDF. Update session_state if provided."""
    doc_name = _safe_doc_name(pdf_path)
    entry = {
        "doc_name": doc_name,
        "stage1_status": "error",
        "stage2_status": "runtime_failure",
        "stage2_iterations_used": 0,
        "stage2_best_accuracy": 0.0,
        "stage2_threshold": THRESHOLD,
        "stage2_max_iters": MAX_ITERS,
        "stage3_accuracy": 0.0,
        "files": _result_paths(doc_name),
    }

    s1, s1_calls = stage1(pdf_path)
    if session_state is not None:
        for c in s1_calls:
            session_state["agent_input_tokens"] += c["input_tokens"] + c["cache_read"] + c["cache_creation"]
            session_state["agent_output_tokens"] += c["output_tokens"]
            session_state["total_llm_calls"] += 1

    if not s1.ok:
        entry["stage1_status"] = s1.status
        return entry
    entry["stage1_status"] = "ok"

    s2, s2_calls = stage2(pdf_path)
    if session_state is not None:
        for c in s2_calls:
            session_state["agent_input_tokens"] += c["input_tokens"] + c["cache_read"] + c["cache_creation"]
            session_state["agent_output_tokens"] += c["output_tokens"]
            session_state["total_llm_calls"] += 1
    if s2 is None:
        return entry
    entry["stage2_status"] = s2.status
    entry["stage2_iterations_used"] = s2.iterations_used
    entry["stage2_best_accuracy"] = round(float(s2.best_accuracy), 6)

    rep = stage3(pdf_path)
    if rep is not None:
        entry["stage3_accuracy"] = round(float(rep.get("accuracy", 0.0)), 6)
    else:
        entry["stage3_accuracy"] = entry["stage2_best_accuracy"]
    return entry


def list_sample_pdfs() -> list[Path]:
    return sorted([p for p in SAMPLE_DIR.iterdir() if p.suffix.lower() == ".pdf"])


def run_all_samples():
    _ensure_dirs()
    pdfs = list_sample_pdfs()
    _print(f"[all-samples] {len(pdfs)} PDF(s) under {SAMPLE_DIR}")
    session_start = time.time()
    timestamp = _now_utc_iso()
    timestamp_compact = _now_utc_stamp()
    log_path = RESULTS_DIR / f"run_log__{MODEL_SHORT}_{timestamp_compact}.json"

    session_state = {
        "agent_input_tokens": 0,
        "agent_output_tokens": 0,
        "total_llm_calls": 0,
    }
    documents = []
    for pdf in pdfs:
        try:
            entry = run_all(pdf, session_state=session_state)
        except Exception as e:
            import traceback as _tb
            _print(f"[all-samples] {pdf.name} crashed: {e}\n{_tb.format_exc()}")
            entry = {
                "doc_name": _safe_doc_name(pdf),
                "stage1_status": "error",
                "stage2_status": "runtime_failure",
                "stage2_iterations_used": 0,
                "stage2_best_accuracy": 0.0,
                "stage2_threshold": THRESHOLD,
                "stage2_max_iters": MAX_ITERS,
                "stage3_accuracy": 0.0,
                "files": _result_paths(_safe_doc_name(pdf)),
                "crash": str(e),
            }
        documents.append(entry)
        # Persist a partial log after each doc so a crash doesn't lose data.
        partial = _build_log(timestamp, session_start, session_state, documents)
        log_path.write_text(json.dumps(partial, indent=2, ensure_ascii=False), encoding="utf-8")

    final_log = _build_log(timestamp, session_start, session_state, documents)
    log_path.write_text(json.dumps(final_log, indent=2, ensure_ascii=False), encoding="utf-8")

    summary = final_log["summary"]
    _print("")
    _print("=== run summary ====================================================")
    _print(f"docs:                {summary['num_docs']}")
    _print(f"  passed:            {summary['num_passed']}")
    _print(f"  below_threshold:   {summary['num_below_threshold']}")
    _print(f"  failed:            {summary['num_failed']}")
    _print(f"macro_avg_accuracy:  {summary['macro_avg_accuracy']:.4f}")
    _print(f"latency_seconds:     {final_log['latency_seconds']:.1f}")
    _print(f"agent_input_tokens:  {final_log['agent_input_tokens']:,}")
    _print(f"agent_output_tokens: {final_log['agent_output_tokens']:,}")
    _print(f"total_llm_calls:     {final_log['total_llm_calls']}")
    _print(f"run log:             {log_path}")
    _print("====================================================================")


def _build_log(timestamp: str, session_start: float, session_state: dict, documents: list[dict]) -> dict:
    num_docs = len(documents)
    num_passed = sum(1 for d in documents if d.get("stage2_status") == "passed")
    num_below = sum(1 for d in documents if d.get("stage2_status") == "below_threshold")
    num_failed = sum(1 for d in documents if d.get("stage2_status") == "runtime_failure"
                     or d.get("stage1_status") != "ok")
    accs = [float(d.get("stage3_accuracy", 0.0)) for d in documents] or [0.0]
    macro_avg = sum(accs) / len(accs) if accs else 0.0
    return {
        "task": "twix2.0 extraction pipeline",
        "model": MODEL,
        "timestamp": timestamp,
        "latency_seconds": round(time.time() - session_start, 3),
        "agent_input_tokens": int(session_state["agent_input_tokens"]),
        "agent_output_tokens": int(session_state["agent_output_tokens"]),
        "total_llm_calls": int(session_state["total_llm_calls"]),
        "documents": documents,
        "summary": {
            "num_docs": num_docs,
            "num_passed": num_passed,
            "num_below_threshold": num_below,
            "num_failed": num_failed,
            "macro_avg_accuracy": round(macro_avg, 6),
        },
    }


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def main():
    parser = argparse.ArgumentParser(description="twix2.0 extraction pipeline orchestrator")
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name in ("stage1", "stage2", "stage3", "all"):
        sp = sub.add_parser(name)
        sp.add_argument("pdf", help="Path to a PDF file")
    sub.add_parser("all-samples")
    args = parser.parse_args()

    if args.cmd == "stage1":
        stage1(Path(args.pdf).resolve())
    elif args.cmd == "stage2":
        stage2(Path(args.pdf).resolve())
    elif args.cmd == "stage3":
        stage3(Path(args.pdf).resolve())
    elif args.cmd == "all":
        session_state = {"agent_input_tokens": 0, "agent_output_tokens": 0, "total_llm_calls": 0}
        run_all(Path(args.pdf).resolve(), session_state=session_state)
    elif args.cmd == "all-samples":
        run_all_samples()


if __name__ == "__main__":
    main()
