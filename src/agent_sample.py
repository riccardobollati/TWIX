"""Task prompt builder for rule generation, to be passed to `claude -p`."""

from __future__ import annotations

import subprocess
from pathlib import Path


TASK_PROMPT = '''\
You are working inside the LSF project root. Your task is to generate a minimal \
set of Python span-retrieval rules for the following question over SEC financial filings.

Use every tool available to you: read files, write files, execute Python scripts, \
run shell commands, search for patterns with grep, and inspect directory contents. \
Do not limit yourself to reasoning alone — actively load documents, run code to \
measure cost and accuracy, and iterate based on the results.

QUESTION: {question}

INPUTS
  Sampled documents:           {doc_list}
  Labels file (ground truth):  {labels_file}
  Document JSON files:         {processing_dir}/<DOC_NAME>_reconstructed.json
  Existing rules to check:     {rules_dir}
  Model (for file naming):     claude-{model_name}

---

DEFINITIONS

Cost (per document)
  Apply the union of all rules to a document. Concatenate the text of every \
returned span. Compute:
    cost = tiktoken_tokens(retrieved_text) / tiktoken_tokens(full_document_text)
  where full_document_text is the concatenation of all spans in doc["texts"].
  avg_cost = mean of cost over all sampled documents.
  A low avg_cost means the rules are selective — they retrieve only the \
relevant fragment instead of large swaths of the document.

Merge accuracy
  For each sampled document, apply every rule, take the union of all returned \
spans (deduplicated by identity), concatenate their text, and pass it to the LLM \
with the question. The document is "correct" if the LLM's answer matches the \
ground truth (judged by a second LLM call for semantic equivalence).
  merge_accuracy = (number of correct documents) / (total sampled documents)
  During iterative development you may use a fast proxy: a document is "hit" if \
the ground truth string appears as a substring (case-insensitive) in the \
retrieved text. Use this proxy to iterate cheaply; call the LLM judge only \
for final verification.

---

OBJECTIVES (in priority order)

1. merge_accuracy >= 0.95 on the sampled documents.
2. avg_cost as small as possible. Target avg_cost < 0.05 (retrieved tokens are \
less than 5% of the full document). After hitting the accuracy threshold, tighten \
high-cost rules without dropping accuracy. If meeting the cost target would require \
sacrificing accuracy, keep accuracy and accept higher cost — accuracy always wins.
3. Fewest rules possible. Prefer one broad rule that covers 8 of 10 documents \
over three narrow rules that each cover 3. A rule covering fewer than 2 documents \
should be merged into a broader rule or dropped.

---

DOCUMENT STRUCTURE

Each document JSON has a "texts" list of span dicts with these fields:
  text            — string content; tables are in Markdown pipe format
  label           — "text" | "section_header" | "table" | "list_item"
  page_no         — integer page number
  bold            — 1 if bold, 0 otherwise
  size            — font size in points
  structure.level — "H1" | "H2" | "H3" | "H4" | "Body"
  structure.path_text — pipe-separated breadcrumb of ancestor section headers
  table_data.cells — list of {{row, col, text, is_column_header, is_row_header}}
                     (only present when label == "table")

RULE INTERFACE

Each rule is a standalone Python function saved as a .py file:

  def rule_<descriptive_name>(doc: dict) -> list[dict]:
      """One-line description of what this rule targets."""
      try:
          return [span for span in doc["texts"] if <condition>]
      except Exception:
          return []

Rules must be self-contained (all imports inside the function body), must never \
raise, and must return a list of span dicts from doc["texts"].

---

WORKFLOW

1. Read existing rules in {rules_dir} first. Understand which structural \
   patterns they exploit (page number, section path, label, font size, keywords \
   in table cells). Do not duplicate patterns that already work well.

2. Load the sampled documents listed under "Sampled documents" above. \
   Each entry is a DOC_NAME (without .pdf or _reconstructed.json). Load each \
   document from {processing_dir}/<DOC_NAME>_reconstructed.json. \
   Then load ground truth answers from {labels_file}: it maps "DOCNAME.pdf" to \
   a dict of question → answer. Extract only the answer for this question and \
   only for the specified sampled documents to build your ground_truth dict. \
   Ignore any documents in the labels file that are not in the sampled list.

3. Study the documents. For each sampled doc, locate the span containing the \
   ground truth answer and note its structural fields (page_no, label, level, \
   bold, path_text). Look for the dominant pattern shared by most documents — \
   that pattern becomes your first, broadest rule.

4. Write the broadest rule first. Test it: compute the hit rate (substring match) \
   and avg_cost across all sampled docs. If avg_cost > 0.05, tighten the filter \
   (add page_no, label, or path_text constraints) and retest.

5. Find uncovered documents — those where no current rule retrieves the answer. \
   Diagnose each by inspecting its answer span's structural fields and comparing \
   them to the passing docs. Write a targeted rule only if it covers at least \
   2 uncovered documents.

6. Repeat steps 4–5 until substring-match coverage is >= 0.95.

7. Run the LLM-judge evaluation using src/rule_apply_merge.py and \
   src/eval_rule.py (or equivalent) to measure merge_accuracy. \
   If merge_accuracy < 0.95: \
   (a) Identify every document the judge marked as wrong. \
   (b) For each failing document, inspect the retrieved spans and compare \
       them against the ground truth answer — determine whether the issue is \
       that the answer span is not retrieved at all, or that it is retrieved \
       but the LLM answers incorrectly (e.g. unit mismatch, wrong row). \
   (c) Fix existing rules or write new targeted rules to address the \
       root cause. Prefer fixing over adding rules; only add a new rule if \
       it covers at least 2 failing documents. \
   (d) Re-run the LLM judge. \
   Repeat (a)–(d) until merge_accuracy >= 0.95 or you have exhausted all \
   diagnosable patterns (document why it is not achievable if so). \
   Only proceed to step 8 once the LLM judge confirms merge_accuracy >= 0.95.

8. If any rule has avg_cost > 0.05, tighten it (narrower page range, stricter \
   label or path_text filter) and re-verify accuracy is preserved.

9. Save each rule as a .py file to {rules_dir}/{question_slug}/. Follow the exact \
   format used by all existing rules in {rules_dir}:
   - One .py file per rule, filename == function name, e.g. rule_page1_bold_name.py
   - Each file contains exactly one top-level function with no imports outside \
     the function body
   - Function signature: def rule_<name>(doc: dict) -> list[dict]:
   - First line of function body: a docstring with a single-line description
   - Wrap the entire body in try/except Exception: return []
   - No helper functions, no module-level variables, no __main__ block
   Example layout:
     def rule_page1_bold_name(doc: dict) -> list[dict]:
         """Match bold page-1 spans containing the company name."""
         try:
             return [s for s in doc.get("texts", [])
                     if s.get("page_no") == 1 and s.get("bold") == 1]
         except Exception:
             return []

10. Record timing and token usage throughout the session, then save a JSON log to \
    {rules_dir}/{question_slug}_rule_gen.json with the following schema:

    {{
      "question":             "<question text>",
      "question_slug":        "<slug>",
      "timestamp":            "<ISO-8601 UTC>",
      "latency_seconds":      <float>,   // wall-clock time from session start to end
      "agent_input_tokens":   <int>,     // cumulative input tokens across all LLM
                                         // calls made by this agent during rule gen
                                         // (QA calls, judge calls, any model calls)
      "agent_output_tokens":  <int>,     // cumulative output tokens from same calls
      "total_llm_calls":      <int>,     // total number of LLM API calls made
      "num_rules":            <int>,
      "merge_accuracy":       <float>,
      "avg_cost_ratio":       <float>,
      "rules": [
        {{
          "rule_name":      "<name>",
          "description":    "<docstring>",
          "coverage":       <int>,       // number of sampled docs this rule hits
          "avg_cost_ratio": <float>,
          "file":           "<path>"
        }}
      ]
    }}

    Track latency by recording time.time() at the very start and again just before \
    writing this file. Track token usage by accumulating prompt_tokens and \
    completion_tokens from the usage field of every LLM API response made during \
    the session (QA calls, judge calls, or any other model calls). Track \
    total_llm_calls by incrementing a counter on each API call.

    Name the log file using the pattern:
      {{question_slug}}_claude-{{model_name}}_{{timestamp}}_rule_gen.json
    where model_name is the short model identifier used in this session \
(e.g. opus-4-5, sonnet-4-5) and timestamp is YYYYMMDD_HHMMSS. \
    Example: what_is_total_revenue_claude-opus-4-5_20260505_143022_rule_gen.json

    Apply the same naming convention to any other output files written during \
    this session (trace logs, intermediate result JSONs), so all files from a \
    run are identifiable by model name.

11. Print a final summary: number of rules, merge_accuracy, avg_cost_ratio, \
    latency_seconds, total token usage, and for each rule: its name, coverage \
    (number of sampled docs it hits), and individual avg_cost_ratio.

---

AVAILABLE SIGNAL TYPES

When studying documents and designing rules, consider every signal listed below. \
A strong rule typically combines two or more signals. Be creative — if you observe \
a pattern not on this list, exploit it.

1. PHYSICAL LOCATION
   Which page(s) does the answer consistently appear on?
   Fields: span["page_no"]
   Example: answer is always on page 1 or 2 → filter page_no <= 2.

2. SEMANTIC LOCATION
   Which named section is the answer under? Use the ancestor breadcrumb or nearby \
   section headers.
   Fields: span["structure"]["path_text"], span["label"] == "section_header"
   Example: answer lives under a span whose path_text contains "Item 8" or \
   "Consolidated Statements".

3. KEYWORD PROXIMITY
   What keywords appear in or near the answer span's own text?
   Fields: span["text"]
   Example: span whose text contains "Employer Identification Number" or "EIN".

4. DATA FEATURE — TABLE STRUCTURE
   Is the answer inside a table? Which row or column header identifies it?
   Fields: span["label"] == "table", span["table_data"]["cells"],
           cell["is_column_header"], cell["is_row_header"], cell["text"]
   Example: table where any row-header cell text matches "Net income" or \
   "Total revenues".

5. TYPOGRAPHY
   Is the answer in a bold, large-font, or all-caps span?
   Fields: span["bold"], span["size"], span["text"].isupper()
   Example: first bold span on page 1 whose text is all-caps (company name).

6. STRUCTURAL POSITION
   What heading level or document depth is the span at?
   Fields: span["structure"]["level"] ("H1"–"H4" or "Body")
   Example: an H1 span near the top of the document.

7. LABEL COMBINATION
   Combine label type with other signals for precision.
   Fields: span["label"] ("text", "section_header", "table", "list_item")
   Example: label == "section_header" AND level == "H2" AND path_text \
   contains "Item 1".

8. SIBLING / POSITIONAL RELATIONSHIP
   The answer span may not contain the keyword itself — it may be the span \
   immediately before or after a landmark span (e.g., a label span followed by \
   a value span).
   Approach: scan doc["texts"] with an index loop; when a landmark is found at \
   index i, return texts[i+1] or texts[i-1].
   Example: span immediately following a bold "State of Incorporation:" label.

9. PAGE RANGE FROM TABLE OF CONTENTS
   The TOC (usually on pages 2–5) lists section names and their page numbers. \
   Parse it to derive which pages contain Item 8 or other target sections, then \
   filter spans to that page range.
   Approach: find a span where path_text or text references "Item 8" and extract \
   the page number from adjacent text; use it to bound page_no.

10. TABLE COLUMN / ROW HEADER PATTERN
    For financial tables, the answer is often in a specific column (e.g., the \
    most recent fiscal year column) of a row identified by its row header.
    Fields: cell["row"], cell["col"], cell["is_column_header"], \
            cell["is_row_header"], cell["text"]
    Example: in a table whose column header row contains a year string, find \
    the cell in the row whose row header matches "Total assets".

11. LIST ITEM POSITION
    If the answer appears in a list, its position (first, last, nth) or its \
    sibling content may be a reliable signal.
    Fields: span["label"] == "list_item", adjacent spans

12. ANY OTHER PATTERN
    Think carefully about each uncovered document. If none of the above signals \
    apply, look for any consistent structural or textual regularity — font size \
    thresholds, span count offsets from document start, repeated preamble \
    patterns, etc. Describe and implement it.

---

DESIGN PRINCIPLES

- Combine signals. A rule using page_no AND label AND a path_text substring is \
  far more precise (lower cost) than any single signal alone.
- Structural anchors generalise better than keywords alone. path_text, page_no, \
  and label patterns are stable across companies and years; exact keyword strings \
  can vary.
- For cover-page facts (name, ticker, address, shares, EIN), the answer is almost \
  always on page 1 or 2 — a page_no filter is cheap and sufficient as a first cut.
- For financial figures (revenue, net income, total assets, debt), anchor on \
  path_text containing section names (Item 8, Consolidated Statements) and \
  restrict to label == "table", then narrow by row/column header content.
- Sibling rules are powerful when the answer span itself is nondescript (a bare \
  number) but its preceding label span is distinctive.
- Do not add a new rule just to push accuracy from 0.95 to 1.0 if doing so \
  doubles avg_cost. The cost objective is real.
'''


_MODEL_ALIASES = {
    "opus":   "claude-opus-4-5",
    "sonnet": "claude-sonnet-4-5",
    "haiku":  "claude-haiku-4-5-20251001",
}


def build_prompt(
    question: str,
    docs: list[str],                    # list of DOC_NAMEs (no .pdf suffix)
    labels_file: str = "data/financebench/sample_doc_labels.json",
    processing_dir: str = "data/financebench/processing",
    rules_dir: str = "rules/financebench_single_cluster/agent/opus47/raw",
    model: str = "opus",
) -> str:
    import re
    question_slug = re.sub(r"[^\w]", "_", question.lower())[:60].rstrip("_")
    doc_list = "\n".join(f"    - {d}" for d in docs) if docs else "    (all docs in labels file)"
    resolved_model = _MODEL_ALIASES.get(model, model)
    # Extract short name after "claude-" for embedding in filenames
    model_name = resolved_model.removeprefix("claude-")
    return TASK_PROMPT.format(
        question=question,
        question_slug=question_slug,
        doc_list=doc_list,
        labels_file=labels_file,
        processing_dir=processing_dir,
        rules_dir=rules_dir,
        model_name=model_name,
    )


def run(
    question: str,
    docs: list[str],                    # list of DOC_NAMEs (no .pdf suffix)
    labels_file: str = "data/financebench/sample_doc_labels.json",
    processing_dir: str = "data/financebench/processing",
    rules_dir: str = "rules/financebench_single_cluster/agent/opus47/raw",
    model: str = "opus",
    cwd: str | None = None,
) -> str:
    prompt = build_prompt(
        question=question,
        docs=docs,
        labels_file=labels_file,
        processing_dir=processing_dir,
        rules_dir=rules_dir,
        model=model,
    )
    resolved_model = _MODEL_ALIASES.get(model, model)
    project_root = cwd or str(Path(__file__).resolve().parent)
    result = subprocess.run(
        ["claude", "--model", resolved_model, "--dangerously-skip-permissions", "-p", prompt],
        capture_output=True,
        text=True,
        cwd=project_root,
        timeout=1800,
    )
    if result.returncode != 0:
        raise RuntimeError(f"claude exited {result.returncode}:\n{result.stderr}")
    return result.stdout


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Generate rules via claude -p.",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument("question",
                        help="The QA question to generate rules for.")
    parser.add_argument("--docs", nargs="+", required=True,
                        metavar="DOC_NAME",
                        help="One or more sampled document names (no .pdf suffix).\n"
                             "Example: --docs AMCOR_2019_10K BOEING_2018_10K")
    parser.add_argument("--labels-file",    default="data/financebench/sample_doc_labels.json")
    parser.add_argument("--processing-dir", default="data/financebench/processing")
    parser.add_argument("--rules-dir",      default="rules/financebench_single_cluster/agent/opus47/raw")
    parser.add_argument("--model",          default="opus",
                        help="Model alias (opus/sonnet/haiku) or full model string.")
    parser.add_argument("--cwd",            default=None)
    parser.add_argument("--print-prompt",   action="store_true",
                        help="Print the prompt and exit without running claude.")
    args = parser.parse_args()

    if args.print_prompt:
        print(build_prompt(args.question, args.docs, args.labels_file,
                           args.processing_dir, args.rules_dir))
    else:
        print(run(args.question, args.docs, args.labels_file,
                  args.processing_dir, args.rules_dir, args.model, args.cwd))
