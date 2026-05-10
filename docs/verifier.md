# Verifier

Compares the agent's extraction (gold) against the code-generated extraction (candidate) for each document, lists every mismatch, explains the likely cause, and writes a markdown report to `analysis/`.

## How it works

For each document the verifier reads three files from `results/`:

| File | Contents |
|---|---|
| `<doc>__opus-4-7.json` | Agent extraction (gold / ground truth) |
| `<doc>__opus-4-7.code_output.json` | Output from running the generated extractor code |
| `<doc>__opus-4-7.eval.json` | Pre-computed diffs and scores (produced by `src/eval/score.py`) |

It then generates `analysis/<doc>__analysis.md` with:

1. **Score summary** — overall accuracy and per-component scores
2. **Record-level mismatches** — missing or extra records
3. **Node-level mismatches** — missing or extra nodes
4. **Type mismatches** — nodes where code chose the wrong type (table / key_value / metadata)
5. **Content mismatches** — field-level value differences, grouped by reason code
6. **Structure mismatches** — wrong parent-child edges or relationship notes

## Mismatch reason codes

| Code | Meaning |
|---|---|
| `R-KV-VALUE-DIFFERS` | Code extracted a wrong value for a key-value field (boundary bleed, bad split) |
| `R-CELL-DIFFERS` | Table cell differs (column alignment, prefix/suffix not stripped) |
| `R-HEADER-DIFFERS` | Column header text does not match |
| `R-HEADER-ORDER` | Headers present but in wrong order |
| `R-ROW-MISSING` | Code missed a table row |
| `R-ROW-EXTRA` | Code produced a spurious table row |
| `R-TYPE-MISMATCH` | Node classified as wrong type |
| `R-NODE-UNALIGNED` | Agent node has no match in code output |
| `R-NODE-EXTRA` | Code produced extra node not in agent output |
| `R-RECORD-MISSING` | Code missed an entire record |
| `R-RECORD-EXTRA` | Code produced an extra record |
| `R-STRUCT-EDGE` | Parent-child edge differs |
| `R-NOTE-DIFFERS` | Relationship note text differs |

## Usage

```bash
# Run for all sample documents (skips docs without complete results)
python src/verifier.py

# Run for a single document
python src/verifier.py Investigations_Redacted
```

Reports are written to `analysis/<doc>__analysis.md`.
