"""Verifier: compare agent results (gold) vs code-generated results for a document.

For each document reads:
  results/<doc>__<model>.json            — agent extraction (gold)
  results/<doc>__<model>.code_output.json — extractor code output (candidate)
  results/<doc>__<model>.eval.json        — pre-computed diffs and scores

Produces:
  analysis/<doc>__analysis.md            — human-readable mismatch report

Usage:
    python src/verifier.py                   # all sample docs
    python src/verifier.py <doc_name>        # one specific doc (stem without model suffix)
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

RESULTS_DIR  = ROOT / "results"
ANALYSIS_DIR = ROOT / "analysis"
MODEL_SHORT  = "opus-4-7"

REASON_EXPLANATIONS = {
    "R-KV-VALUE-DIFFERS":  "Code extracted a different value for this key-value field. Common causes: boundary bleed (extra surrounding text captured), text split at wrong position.",
    "R-CELL-DIFFERS":      "Table cell value differs from agent. Common causes: column alignment off, row prefix/suffix not stripped, merged-cell mis-handling.",
    "R-HEADER-DIFFERS":    "Table header text does not match. The code likely extracted a different column name or included extraneous characters.",
    "R-HEADER-ORDER":      "Table headers are present but in a different order. The code may be reading columns left-to-right differently than the agent.",
    "R-ROW-MISSING":       "Code missed a table row that the agent captured. The row may have been skipped due to a parsing boundary or pagination gap.",
    "R-ROW-EXTRA":         "Code produced a table row not present in agent output. Could be a spurious line (header repeated, footer row) being treated as data.",
    "R-TYPE-MISMATCH":     "Code classified the node as a different type than the agent (e.g., table vs key_value). Indicates structural mis-identification.",
    "R-NODE-UNALIGNED":    "Agent node has no matching node in code output. The node was likely not extracted at all.",
    "R-NODE-EXTRA":        "Code produced an extra node not present in agent output. Could be a duplicate or a spurious block.",
    "R-RECORD-MISSING":    "Code missed an entire record that the agent identified.",
    "R-RECORD-EXTRA":      "Code produced an extra record not present in agent output.",
    "R-STRUCT-EDGE":       "Parent-child relationship (edge) differs. Code linked the node to a different parent.",
    "R-NOTE-DIFFERS":      "Relationship note text differs between agent and code output.",
}


def _safe_doc_name(pdf_path: Path) -> str:
    return pdf_path.stem.replace("/", "_").replace(" ", "_")


def _result_paths(doc_name: str) -> dict[str, Path]:
    return {
        "gold":        RESULTS_DIR / f"{doc_name}__{MODEL_SHORT}.json",
        "code_output": RESULTS_DIR / f"{doc_name}__{MODEL_SHORT}.code_output.json",
        "eval":        RESULTS_DIR / f"{doc_name}__{MODEL_SHORT}.eval.json",
    }


def _explain(reason: str) -> str:
    return REASON_EXPLANATIONS.get(reason, reason)


def _truncate(s: str, n: int = 80) -> str:
    s = str(s)
    return s if len(s) <= n else s[:n] + "…"


def verify_doc(doc_name: str) -> Path:
    """Generate analysis/<doc>__analysis.md for one document. Returns the output path."""
    paths = _result_paths(doc_name)
    for label, p in paths.items():
        if not p.exists():
            raise FileNotFoundError(f"{label} file not found: {p}")

    gold     = json.loads(paths["gold"].read_text(encoding="utf-8"))
    code_out = json.loads(paths["code_output"].read_text(encoding="utf-8"))
    ev       = json.loads(paths["eval"].read_text(encoding="utf-8"))

    accuracy   = float(ev.get("accuracy", 0.0))
    components = ev.get("components", {})
    content_diffs    = ev.get("content_diffs",    [])
    structure_diffs  = ev.get("structure_diffs",  [])
    type_mismatches  = ev.get("type_mismatches",  [])
    missing_nodes    = ev.get("missing_gold_nodes",      [])
    extra_nodes      = ev.get("extra_candidate_nodes",   [])
    missing_records  = ev.get("missing_gold_records",    [])
    extra_records    = ev.get("extra_candidate_records", [])

    n_gold_records = len(gold.get("records", []))
    n_code_records = len(code_out.get("records", []))

    lines: list[str] = []

    def h1(t: str): lines.append(f"# {t}\n")
    def h2(t: str): lines.append(f"## {t}\n")
    def h3(t: str): lines.append(f"### {t}\n")
    def p(t: str):  lines.append(f"{t}\n")
    def sep():      lines.append("---\n")

    # ── Header ──────────────────────────────────────────────────────────────────
    h1(f"Verification Report — `{doc_name}`")
    p(f"**Model:** {ev.get('reference_model', MODEL_SHORT)}  ")
    p(f"**Overall accuracy:** {accuracy:.4f}  ")
    p(f"**Records — agent:** {n_gold_records}  |  **code:** {n_code_records}\n")

    # ── Component scores ─────────────────────────────────────────────────────────
    h2("Score Components")
    lines.append("| Component | Score |")
    lines.append("|---|---|")
    nm = components.get("NodeMatchF1", {})
    lines.append(f"| NodeMatchF1 (precision / recall) | {nm.get('precision', 0):.4f} / {nm.get('recall', 0):.4f} |")
    cs = components.get("ContentScore", {})
    lines.append(f"| ContentScore (overall) | {cs.get('overall', 0):.4f} |")
    by_type = cs.get("by_type", {})
    for t, v in by_type.items():
        v_str = f"{v:.4f}" if v is not None else "N/A"
        lines.append(f"| ContentScore — {t} | {v_str} |")
    ss = components.get("StructureScore", {})
    lines.append(f"| StructureScore (edge / path / note) | {ss.get('edge_accuracy', 0):.4f} / {ss.get('path_accuracy', 0):.4f} / {ss.get('note_agreement_rate', 0):.4f} |")
    lines.append("")

    total_issues = (len(content_diffs) + len(structure_diffs) + len(type_mismatches)
                    + len(missing_nodes) + len(extra_nodes)
                    + len(missing_records) + len(extra_records))

    if total_issues == 0:
        sep()
        p("**No mismatches found.** Agent and code outputs are identical.")
        return _write(doc_name, lines)

    p(f"**Total mismatches:** {total_issues}\n")
    sep()

    # ── Missing / extra records ──────────────────────────────────────────────────
    if missing_records or extra_records:
        h2("Record-Level Mismatches")
        if missing_records:
            h3(f"Missing Records ({len(missing_records)})")
            p(_explain("R-RECORD-MISSING"))
            lines.append("| Record ID |")
            lines.append("|---|")
            for r in missing_records:
                lines.append(f"| {r} |")
            lines.append("")
        if extra_records:
            h3(f"Extra Records ({len(extra_records)})")
            p(_explain("R-RECORD-EXTRA"))
            lines.append("| Record ID |")
            lines.append("|---|")
            for r in extra_records:
                lines.append(f"| {r} |")
            lines.append("")

    # ── Missing / extra nodes ────────────────────────────────────────────────────
    if missing_nodes or extra_nodes:
        h2("Node-Level Mismatches")
        if missing_nodes:
            h3(f"Missing Nodes ({len(missing_nodes)})")
            p(_explain("R-NODE-UNALIGNED"))
            lines.append("| Record | Node ID | Type | Reason |")
            lines.append("|---|---|---|---|")
            for n in missing_nodes:
                lines.append(f"| {n.get('gold_record_id','')} | {n.get('gold_id','')} | {n.get('type','')} | {n.get('reason','')} |")
            lines.append("")
        if extra_nodes:
            h3(f"Extra Nodes ({len(extra_nodes)})")
            p(_explain("R-NODE-EXTRA"))
            lines.append("| Record | Node ID | Type | Reason |")
            lines.append("|---|---|---|---|")
            for n in extra_nodes:
                lines.append(f"| {n.get('candidate_record_id','')} | {n.get('candidate_id','')} | {n.get('type','')} | {n.get('reason','')} |")
            lines.append("")

    # ── Type mismatches ──────────────────────────────────────────────────────────
    if type_mismatches:
        h2(f"Type Mismatches ({len(type_mismatches)})")
        p(_explain("R-TYPE-MISMATCH"))
        lines.append("| Record | Node ID | Agent Type | Code Type |")
        lines.append("|---|---|---|---|")
        for m in type_mismatches:
            lines.append(f"| {m.get('gold_record_id','')} | {m.get('gold_id','')} | {m.get('gold_type','')} | {m.get('candidate_type','')} |")
        lines.append("")

    # ── Content diffs ────────────────────────────────────────────────────────────
    if content_diffs:
        h2(f"Content Mismatches ({len(content_diffs)})")
        by_reason: dict[str, list] = defaultdict(list)
        for d in content_diffs:
            by_reason[d.get("reason", "unknown")].append(d)

        for reason, items in sorted(by_reason.items()):
            h3(f"{reason} — {len(items)} occurrence(s)")
            p(f"**Explanation:** {_explain(reason)}")
            lines.append("")
            lines.append("| Record | Node | Field | Agent value | Code value |")
            lines.append("|---|---|---|---|---|")
            for d in items:
                lines.append(
                    f"| {d.get('gold_record_id','')} "
                    f"| {d.get('gold_id','')} "
                    f"| {_truncate(d.get('field',''), 50)} "
                    f"| {_truncate(d.get('gold',''), 60)} "
                    f"| {_truncate(d.get('candidate',''), 60)} |"
                )
            lines.append("")

    # ── Structure diffs ──────────────────────────────────────────────────────────
    if structure_diffs:
        h2(f"Structure Mismatches ({len(structure_diffs)})")
        by_reason2: dict[str, list] = defaultdict(list)
        for d in structure_diffs:
            by_reason2[d.get("reason", "unknown")].append(d)

        for reason, items in sorted(by_reason2.items()):
            h3(f"{reason} — {len(items)} occurrence(s)")
            p(f"**Explanation:** {_explain(reason)}")
            lines.append("")
            lines.append("| Record | Node | Detail |")
            lines.append("|---|---|---|")
            for d in items:
                detail = d.get("detail") or d.get("note") or ""
                lines.append(f"| {d.get('gold_record_id','')} | {d.get('gold_id','')} | {_truncate(detail, 80)} |")
            lines.append("")

    return _write(doc_name, lines)


def _write(doc_name: str, lines: list[str]) -> Path:
    ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)
    out = ANALYSIS_DIR / f"{doc_name}__{MODEL_SHORT}__analysis.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    return out


def list_sample_docs() -> list[str]:
    from src.run_pipeline import SAMPLE_DIR
    docs = []
    for pdf in sorted(SAMPLE_DIR.glob("*.pdf")):
        doc_name = _safe_doc_name(pdf)
        paths = _result_paths(doc_name)
        if all(p.exists() for p in paths.values()):
            docs.append(doc_name)
    return docs


def main():
    import argparse
    parser = argparse.ArgumentParser(description="twix2.0 verifier")
    parser.add_argument("doc_name", nargs="?", help="Specific doc name to verify (default: all sample docs)")
    parser.add_argument("--tag", default=None, help="Result file tag/suffix (default: opus-4-7)")
    args = parser.parse_args()

    global MODEL_SHORT
    if args.tag:
        MODEL_SHORT = args.tag

    if args.doc_name:
        targets = [args.doc_name]
    else:
        targets = list_sample_docs()
        if not targets:
            print("No completed sample docs found in results/.")
            return

    for doc_name in targets:
        try:
            out = verify_doc(doc_name)
            ev = json.loads((RESULTS_DIR / f"{doc_name}__{MODEL_SHORT}.eval.json").read_text())
            acc = float(ev.get("accuracy", 0.0))
            n_diffs = (len(ev.get("content_diffs", [])) + len(ev.get("structure_diffs", []))
                       + len(ev.get("type_mismatches", [])) + len(ev.get("missing_gold_nodes", []))
                       + len(ev.get("extra_candidate_nodes", [])))
            print(f"[verifier] {doc_name}: acc={acc:.4f}, {n_diffs} mismatch(es) -> {out}")
        except Exception as e:
            import traceback
            print(f"[verifier] {doc_name}: ERROR — {e}")
            traceback.print_exc()


if __name__ == "__main__":
    main()
