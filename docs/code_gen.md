# Agent-Driven Code Generation for Extraction

This document specifies the **second stage** of the pipeline. It assumes the first stage (`agent_data_extraction.md`) has already produced a JSON tree describing the data in a sampled PDF. That JSON is treated as **ground truth** for this stage.

The goal here is to ask an LLM agent to **write code** that, when run on the same PDF, produces output that matches the agent-extracted JSON — *without* the LLM being in the loop at run time. The agent iterates: it writes code, runs it, scores its output against the ground-truth JSON using the **eval procedure defined in `eval.md`**, and refines until the eval `accuracy` clears a configurable threshold (default `τ = 0.9`) or the iteration budget is exhausted.

Why this matters: stage 1 only sees the first 5 sample pages and is expensive to run on thousands of pages. Stage 2 produces a deterministic, reusable extractor that can be applied to the **full** PDF (and to other PDFs generated from the same template) at near-zero cost.

---

## 1. Pipeline Overview

```
Inputs
  ├── sample.pdf                         (from stage 1)
  └── results/<doc>__<model>.json        (agent ground truth from stage 1)
                       │
                       ▼
              ┌───────────────────┐
              │  Code-gen agent   │ ◄──────────────────┐
              └────────┬──────────┘                    │
                       │ writes / edits                │
                       ▼                               │
                extractor.py                           │
                       │                               │
                       ▼                               │
                  run on sample.pdf                    │
                       │                               │
                       ▼                               │
                 candidate.json                        │
                       │                               │
                       ▼                               │
              ┌────────────────────────┐               │
              │   Evaluator (eval.md)  │               │
              │   accuracy(gold,       │               │
              │            candidate)  │               │
              └────────────┬───────────┘               │
                           │                           │
                  ┌────────┴─────────┐                 │
                  │                  │                 │
            accuracy ≥ τ       accuracy < τ ── feedback ┘
                  │            (eval.json + traceback)
                  ▼
              DONE: save extractor.py and final eval.json
```

---

## 2. Inputs

The code-gen stage takes three things:

1. **`sample.pdf`** — the same first-5-pages sample used in stage 1.
2. **`gold.json`** — the agent's stage-1 output for that sample, loaded from `results/<doc_name>__<model>.json`.
3. **The full PDF path** — used only at the very end, after the extractor has been verified on the sample, to optionally produce a full-document extraction.

The agent **must not** be given the full PDF during code generation. Generation and verification happen entirely against the sample so the gold remains a fair target.

---

## 3. The Extractor Contract

The agent is asked to produce a single Python module, `extractor.py`, exposing one function:

```python
def extract(pdf_path: str) -> dict:
    """
    Read the PDF at pdf_path and return a JSON-serializable dict
    in the exact same shape as the stage-1 agent output:

        {
          "doc_name": "...",
          "model": "code-extractor",   # see §6
          "sampled_pages": 5,
          "records": [
            {
              "record_id": "r1",
              "nodes": [ {id, type, content, relationship}, ... ]
            },
            ...
          ]
        }
    """
```

The contract is identical to stage 1 (see `agent_data_extraction.md` §4) so that comparison is a direct structural diff. The extractor is responsible for **identifying record boundaries** in the PDF and emitting one entry per record under `records`. Even when the document contains a single record, `records` must still be a list of length 1.

Allowed dependencies (kept conservative so the script is portable):

- `pypdf` / `pdfplumber` for text and table extraction
- `re` for regex
- standard library only otherwise

The agent should prefer **layout-aware** parsing (positions, lines, table boundaries) over loose regex when possible, because the same template will be reused across thousands of pages and brittle regex tends to break on edge cases.

---

## 4. The Iterative Refinement Loop

The agent runs in a loop with two roles:

- **Author** — proposes the next version of `extractor.py`.
- **Evaluator** — runs the script on `sample.pdf` and scores the candidate output against `gold.json` using the procedure in `eval.md` (§§3–6). The Evaluator returns a single `accuracy ∈ [0, 1]` plus the full structured `eval.json` diagnostics (alignment, missing/extra nodes, content_diffs, structure_diffs).

The loop is deliberately **iteration-greedy**: by default it does **not** stop early on lack of progress. The Author keeps getting chances until either it clears the threshold or it exhausts the budget. This is intentional — small refactors of the parser often plateau for a few iterations before another correction unlocks several improvements at once.

Configurable parameters (with defaults):

| Param          | Default | Meaning                                                 |
|----------------|---------|---------------------------------------------------------|
| `MAX_ITERS`    | `25`    | Hard cap on Author iterations.                          |
| `THRESHOLD τ`  | `0.9`   | Minimum eval `accuracy` required to declare success.    |
| `EARLY_STOP_ON_NO_PROGRESS` | `False` | If `True`, stop when `accuracy` hasn't improved by `≥ ε = 0.01` for `PATIENCE = 5` consecutive iterations. **Off by default** so the agent gets to use the full budget. |
| `RUN_TIMEOUT_S`| `60`    | Per-iteration extractor wall-clock timeout (see §7).    |

Pseudocode:

```python
from eval import score as eval_score   # implements eval.md §§3–6

THRESHOLD = 0.9
MAX_ITERS = 25

gold = load_json("results/<doc>__<model>.json")

history = []           # rolling list of (code, eval_report) pairs
best    = {"accuracy": -1, "code": None, "candidate": None, "report": None}

for iteration in range(1, MAX_ITERS + 1):
    code = agent.author(
        gold       = gold,
        sample     = "sample.pdf",
        history    = history,                # what's been tried + why it scored low
        threshold  = THRESHOLD,              # tell the Author the bar it needs to clear
    )

    write_file("extractor.py", code)
    candidate, run_err = run_extractor("extractor.py", "sample.pdf")

    if run_err is not None:
        # Treat runtime failure as accuracy = 0 with a special "runtime_error" diagnostic.
        report = {"accuracy": 0.0, "runtime_error": run_err}
    else:
        report = eval_score(gold=gold, candidate=candidate, reference="agent")
        # `report` is exactly the eval.json shape from eval.md §7.

    history.append({"iter": iteration, "accuracy": report["accuracy"], "report": report})

    if report["accuracy"] > best["accuracy"]:
        best = {"accuracy": report["accuracy"], "code": code,
                "candidate": candidate, "report": report}

    if report["accuracy"] >= THRESHOLD:
        break          # success

return best, history
```

Stopping conditions, in order of priority:

1. **Threshold cleared.** `report["accuracy"] >= τ` → success. Save `extractor.py` and the final `eval.json`.
2. **Budget exhausted.** `iteration == MAX_ITERS` → save the **best** scoring candidate seen across the loop (not necessarily the last) and mark `status = "below_threshold"`.
3. **(Disabled by default) No progress.** If `EARLY_STOP_ON_NO_PROGRESS` is enabled and `accuracy` has not improved by at least `ε` for `PATIENCE` iterations, stop and surface the failure. Off by default to give the Author the most chances.

The Author prompt on each iteration must include:

- The full `gold.json`.
- The current `extractor.py` (if any).
- The previous iteration's full `eval.json`, with the structured `content_diffs`, `missing_gold_nodes`, `extra_candidate_nodes`, and `structure_diffs` lists (see `eval.md` §7) — these are exactly the cues a programmer would use to fix the parser.
- Any runtime errors / tracebacks from the previous run.
- The current `accuracy` and the target `THRESHOLD`, framed as an explicit bar to clear.
- A clear instruction to *modify the existing code* rather than rewriting from scratch unless the previous approach is fundamentally wrong (signaled by very low accuracy *and* a structurally different error pattern from prior iterations).

---

## 5. Verification — Defer to `eval.md`

This stage does **not** define its own match rules. The single source of truth for "does the candidate match the gold?" is `eval.md`. Specifically:

- Node alignment: `eval.md` §3 (Hungarian assignment over a type/content/structure similarity matrix; node ids are not assumed equal).
- Per-type content scoring (`table`, `key_value`, `metadata`): `eval.md` §5.
- Parent-edge agreement: `eval.md` §6.
- String normalization (whitespace, case, punctuation, numeric tolerance): `eval.md` §3.4.
- Diagnostic output shape (`alignment`, `content_diffs`, `missing_gold_nodes`, `extra_candidate_nodes`, `structure_diffs`): `eval.md` §7.

Stage 2 only adds the **threshold rule**:

```
match := (eval_report["accuracy"] >= THRESHOLD)
```

with `THRESHOLD = 0.9` by default. Reasoning: requiring strict equality (`accuracy == 1.0`) makes the loop very brittle to harmless OCR-level noise (a non-breaking space, a hyphen vs en-dash, etc.). `0.9` is high enough that the extractor is structurally correct and substantively right on content, while leaving room for those near-equivalences to be tolerated. The threshold is configurable per run.

For the loop's purposes, the Evaluator returns the `eval.json` object verbatim — no summarization or transformation. The Author sees the same diagnostics a human reviewer would see.

---

## 6. Outputs

When the loop finishes, write the following files alongside the gold JSON:

```
results/
├── <doc_name>__<model>.json                   # gold (from stage 1)
├── <doc_name>__<model>.extractor.py           # the best extractor seen
├── <doc_name>__<model>.code_output.json       # best extractor's output on the sample
├── <doc_name>__<model>.eval.json              # final eval.json (eval.md §7)
├── <doc_name>__<model>.eval.txt               # human-readable mismatch analysis (eval.md §8)
└── <doc_name>__<model>.codegen_log.json       # iteration trace
```

`code_output.json` follows the same schema as the gold but with `"model": "code-extractor"` so its provenance is unambiguous.

`eval.json` and `eval.txt` are produced by the Evaluator (see `eval.md`). They reflect the **final, best** candidate — i.e. the one that cleared `τ`, or, if the budget was exhausted, the highest-`accuracy` candidate seen during the loop.

`codegen_log.json` records the full loop, e.g.:

```json
{
  "status": "passed" | "below_threshold" | "runtime_failure",
  "threshold": 0.9,
  "iterations_used": 7,
  "max_iters": 25,
  "best_iteration": 6,
  "best_accuracy": 0.93,
  "accuracy_history": [0.00, 0.42, 0.71, 0.78, 0.85, 0.91, 0.93],
  "history": [
    {"iter": 1, "accuracy": 0.0,  "summary": "TypeError in extract(): pdf had no extractable text"},
    {"iter": 2, "accuracy": 0.42, "summary": "tables found but headers off by one column"},
    {"iter": 6, "accuracy": 0.91, "summary": "all tables matched; one key_value row still missing"},
    {"iter": 7, "accuracy": 0.93, "summary": "fixed key_value; cleared threshold"}
  ]
}
```

---

## 7. Sandboxing & Safety

Generated code is executed locally during the loop, so:

- Run `extractor.py` in a subprocess with a wall-clock timeout (e.g. 60s).
- Treat any non-zero exit, exception, or timeout as a "diff" the Author must fix on the next iteration — capture stdout/stderr and pass it back as part of the feedback.
- Disallow network access in the subprocess (the extractor should only read the local PDF). Easy enforcement: run in an offline subprocess and reject `import requests`/`urllib.request` usage with a static check.
- The extractor must not write outside the `results/` directory.

---

## 8. Suggested Project Layout

Building on the layout from `agent_data_extraction.md`:

```
twix2.0/
├── data/                                 # source PDFs
├── docs/
│   ├── agent_data_extraction.md          # stage 1 spec
│   └── code_gen.md                       # this file
├── results/                              # gold + generated extractors + diffs
└── src/
    ├── data_extraction/                  # stage 1
    │   ├── sample_pdf.py
    │   ├── prompt.py
    │   ├── agent.py
    │   └── run.py
    └── code_gen/                         # stage 2
        ├── author.py                     # builds the Author prompt, calls the model
        ├── runner.py                     # subprocess sandbox per §7
        └── loop.py                       # ties it all together (calls src/eval/score.py)
```

---

## 9. Validation Checklist

Before considering a code-gen run successful:

1. `extractor.py` runs to completion on `sample.pdf` with no exceptions.
2. `extract(pdf_path)` returns a dict that passes the stage-1 schema validation (see `agent_data_extraction.md` §7).
3. The Evaluator (per `eval.md`) reports `accuracy >= THRESHOLD` (default `0.9`).
4. The same `extractor.py` re-run on the sample produces byte-identical `code_output.json` (determinism check).
5. All output files listed in §6 exist and are well-formed JSON / Python / text.
6. The `codegen_log.json` reflects what actually happened: `iterations_used <= MAX_ITERS`, `best_accuracy` matches the saved `eval.json`, and `accuracy_history` is monotone-non-decreasing in `best_accuracy` (it can wiggle iteration to iteration; the *running max* should not).
7. (Optional but recommended) Run `extractor.py` on the **full** PDF and spot-check a handful of records against the source. Stage 2 success on the sample does not guarantee correctness on out-of-sample pages — surface anomalies to the human.
