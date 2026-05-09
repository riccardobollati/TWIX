"""Stage 2 — Author prompt builder + invocation.

The Author is asked to write/edit `extractor.py`. We pass it the gold JSON,
the current extractor (if any), the previous eval.json + eval.txt, any
runtime traceback, and the threshold target.
"""

from __future__ import annotations

import json
from pathlib import Path

from ..data_extraction.agent import CallResult, call_claude


AUTHOR_PROMPT_TEMPLATE = """\
You are a code-generation agent. Your job: write a Python module that, when
run on a sample PDF, produces a JSON tree that matches the gold JSON below.

You will iterate until the eval accuracy clears the threshold or the budget is
exhausted. This is iteration {iteration} of {max_iters}. Current best
accuracy so far: {best_accuracy}. Target threshold: {threshold}.

CONTRACT
The extractor must define one function:

    def extract(pdf_path: str) -> dict:
        # returns a dict matching the gold schema below

Allowed imports: pypdf, pdfplumber, re, plus standard library. No network. No
subprocess. No file writes outside the current working directory.

The returned dict shape must match the gold — records-based format:
{{
  "doc_name": "<basename of source pdf, no extension>",
  "model": "code-extractor",
  "sampled_pages": <int>,
  "records": [
    {{
      "record_id": "<e.g. r1, r2, ...>",
      "nodes": [ ...nodes per spec... ]
    }},
    ...
  ]
}}

"records" is ALWAYS a list, even for single-record documents.
Each record has a unique "record_id" and a flat "nodes" list.
Node ids are unique WITHIN a record; they may repeat across records.
relationship.parent_id must refer to a node id IN THE SAME RECORD only.

Each node has fields: id, type, content, relationship.
- type ∈ {{"table", "key_value", "metadata"}}
- table content: {{"headers": [...], "rows": [[ {{key, value}}, ... ]]}}; each
  row's length equals headers length; each row entry's key matches its header.
- key_value content: list of {{"key": str, "value": str}} pairs.
- metadata content: list of strings.
- relationship: {{"parent_id": <id|null>, "note": "<string>"}}
- parent_id must be null or a valid id within the SAME record. No cycles.
  No cross-record parent_id references.

INPUTS
  Sample PDF path:  {sample_pdf_path}
  Output extractor path (write here): {extractor_path}

GOLD JSON (this is the target — your extractor's output, when run on the
sample PDF, should match this):
```json
{gold_json}
```

{previous_block}

ITERATIVE EVAL-AND-IMPROVE WORKFLOW
Each iteration your task is:
  1. Study the eval feedback below (eval.json + eval.txt) to identify exactly
     which nodes are missing, mismatched, wrong type, or have incorrect content.
  2. Make targeted code edits to fix those specific failures — don't refactor
     what is already working.
  3. The orchestrator will run your updated extractor on the sample PDF and
     re-score it against the gold JSON using the eval procedure (eval.md).
  4. Your score is reported back at the next iteration. Repeat until accuracy
     >= {threshold} or the iteration budget ({max_iters} total) is exhausted.
Goal: the code extractor's output, when run on the sample PDF, must match the
gold JSON at eval accuracy >= {threshold}. Accuracy is the harmonic mean of
NodeMatchF1, ContentScore, and StructureScore as defined in eval.md.

INSTRUCTIONS
1. {action_instruction}
2. Save the new code to: {extractor_path} (use the Write tool).
3. Do NOT run the extractor; the orchestrator will run it. Do not print code
   to stdout.
4. The module must be self-contained. Inside the function body do all heavy
   lifting (parse the PDF, build the nodes list, return the dict).
5. Prefer LAYOUT-AWARE parsing (pdfplumber tables, line positions) over loose
   regex when possible. The same template will be reused on thousands of
   pages, so robustness matters.
6. Match strings exactly when possible; the eval normalizes whitespace, case,
   smart-quotes, and en-dashes (eval.md §3.4) but does NOT fix wrong text.
7. Make sure every table row's `key` field matches the corresponding header.
   Schema validation will reject mismatched keys.
8. When in doubt about whether a block is metadata vs key_value: a key_value
   block has visible Key: Value pairs; metadata is free text / banners /
   titles / disclaimers.
9. Keep node ids consistent across iterations only if you have a reason; the
   evaluator aligns by content so ids do not need to match the gold.
10. Print only a short one-line confirmation when done (e.g. "wrote
    extractor.py").

Begin now.
"""


def _truncate_text(text: str, max_chars: int) -> str:
    if not text:
        return ""
    if len(text) <= max_chars:
        return text
    head = max_chars // 2
    tail = max_chars - head - 80
    return text[:head] + "\n... (truncated " + str(len(text) - max_chars + 80) + " chars) ...\n" + text[-tail:]


def build_author_prompt(
    gold: dict,
    iteration: int,
    max_iters: int,
    best_accuracy: float,
    current_accuracy: float | None,
    threshold: float,
    sample_pdf_path: str,
    extractor_path: str,
    current_extractor_code: str | None,
    last_eval_json: dict | None,
    last_eval_txt: str | None,
    last_runtime_error: str | None,
) -> str:
    gold_json_str = json.dumps(gold, indent=2, ensure_ascii=False)
    if len(gold_json_str) > 60000:
        gold_json_str = _truncate_text(gold_json_str, 60000)

    previous_block_parts = []
    if iteration == 1 and current_extractor_code is None:
        previous_block_parts.append("This is the FIRST iteration; no previous extractor exists.")
        action_instruction = "Author the FIRST version of extractor.py from scratch using the gold JSON as the target."
    else:
        if current_extractor_code is not None:
            code_snippet = _truncate_text(current_extractor_code, 18000)
            previous_block_parts.append(
                "Previous extractor.py (the version we just ran):\n```python\n"
                + code_snippet
                + "\n```"
            )
        if last_runtime_error:
            previous_block_parts.append(
                "Previous run produced a RUNTIME ERROR (treat as accuracy 0):\n"
                + _truncate_text(last_runtime_error, 4000)
            )
            action_instruction = (
                "FIX the runtime error first; then improve accuracy. Modify the "
                "existing code; do not rewrite from scratch unless the previous "
                "approach is fundamentally wrong."
            )
        else:
            action_instruction = (
                "Modify the existing extractor.py to fix the mismatches listed below. "
                "Preserve what works; make minimal, targeted edits. Do not rewrite "
                "from scratch unless the previous approach is fundamentally broken "
                "(very low accuracy AND a structurally different error pattern)."
            )
        if current_accuracy is not None:
            previous_block_parts.append(
                f"Previous iteration accuracy: {current_accuracy:.4f} "
                f"(threshold = {threshold})."
            )
        if last_eval_json is not None:
            try:
                eval_str = json.dumps(last_eval_json, indent=2, ensure_ascii=False)
            except Exception:
                eval_str = str(last_eval_json)
            eval_str = _truncate_text(eval_str, 18000)
            previous_block_parts.append(
                "Previous eval.json (full diagnostic):\n```json\n" + eval_str + "\n```"
            )
        if last_eval_txt is not None:
            previous_block_parts.append(
                "Previous eval.txt (human-readable mismatch report):\n```\n"
                + _truncate_text(last_eval_txt, 12000)
                + "\n```"
            )

    previous_block = "\n\n".join(previous_block_parts) if previous_block_parts else ""

    return AUTHOR_PROMPT_TEMPLATE.format(
        iteration=iteration,
        max_iters=max_iters,
        best_accuracy=f"{best_accuracy:.4f}" if best_accuracy >= 0 else "n/a",
        threshold=threshold,
        sample_pdf_path=sample_pdf_path,
        extractor_path=extractor_path,
        gold_json=gold_json_str,
        previous_block=previous_block,
        action_instruction=action_instruction,
    )


def call_author(
    prompt: str,
    model: str = "claude-opus-4-7",
    cwd: str | Path | None = None,
    add_dirs: list[str] | None = None,
    timeout_s: int = 1800,
) -> CallResult:
    return call_claude(
        prompt=prompt,
        model=model,
        cwd=cwd,
        add_dirs=add_dirs,
        timeout_s=timeout_s,
    )
