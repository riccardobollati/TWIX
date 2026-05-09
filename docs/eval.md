# Evaluation

This document specifies the **third stage** of the pipeline: evaluating how accurate the extracted data is, both for the **agent extraction** (stage 1) and the **code-generated extraction** (stage 2). The output of evaluation is a single quantitative *accuracy score* in `[0, 1]`, plus a breakdown that explains where the score comes from.

The central comparison is between two JSON trees of the shape defined in `agent_data_extraction.md` §4. Ideally the two trees are *exactly* equal — same set of nodes, same types, same content, same parent edges. Equality is rare in practice, so the rest of this document defines a principled way to measure how *close* they are.

---

## 1. What Gets Compared

There are three meaningful comparisons. All three use the same scoring algorithm (§3–§6); they differ only in what plays the role of "reference".

| Comparison         | Reference (gold)                      | Candidate                          | What it measures                                  |
|--------------------|---------------------------------------|------------------------------------|---------------------------------------------------|
| **Agent vs human** | Human-labeled JSON tree (if available) | Stage-1 agent output               | How accurate the agent extraction is.             |
| **Code vs human**  | Human-labeled JSON tree                | Stage-2 code-extractor output      | How accurate the generated extractor is.          |
| **Code vs agent**  | Stage-1 agent output                   | Stage-2 code-extractor output      | How faithfully the code reproduces the agent — the loop's own success criterion (also used by stage 2 verification, but here we report a continuous score, not just match / no-match). |

When no human gold exists, the agent output is treated as the reference for the code comparison. The eval report makes the chosen reference explicit.

---

## 2. Top-Level Score

The headline number is:

```
accuracy = 0.40 * NodeMatchF1
         + 0.40 * ContentScore
         + 0.20 * StructureScore
```

All three components live in `[0, 1]`, so `accuracy ∈ [0, 1]`.

- **`NodeMatchF1`** — do the two trees contain the same nodes? (§4)
- **`ContentScore`** — for the nodes that match, do their contents agree? (§5)
- **`StructureScore`** — do the parent edges in the tree agree? (§6)

A score of `1.0` means the two trees are equal under the normalization rules of §3.4. A score of `0.0` means no node could be aligned at all. Weights are defaults; they're configurable so different downstream uses can emphasize different aspects (e.g. a table-heavy use case may want to upweight `ContentScore`).

The eval report also surfaces a binary `exact_match` flag (`accuracy == 1.0` and every diff list empty) so that "exactly equal" is still callable when you need it.

---

## 3. Alignment

Both gold and candidate JSON have a top-level list of **records**, and each record contains a list of **nodes** (`agent_data_extraction.md` §4.1). Alignment is therefore two-level: records first, then nodes within each matched record pair. Record `record_id`s and node `id`s are arbitrary labels and are not assumed to match — alignment is purely structural.

### 3.0 Record alignment

Let `G_records` and `C_records` be the record lists from gold and candidate. For every pair `(G_r, C_r)`, compute a record-level similarity:

```
record_sim(G_r, C_r) =
    0.50 * mean_pairwise_node_sim(G_r.nodes, C_r.nodes)
                                            # mean of best per-gold-node sim,
                                            # under §3.1 with structure_sim = 0
  + 0.20 * type_multiset_jaccard(G_r.nodes, C_r.nodes)
                                            # how similar the *type histograms* are
                                            # (e.g. "2 tables, 1 kv, 1 metadata")
  + 0.10 * size_similarity(|G_r.nodes|, |C_r.nodes|)
                                            # 1 - |Δ| / max(...) ; penalizes
                                            # very different record sizes
  + 0.20 * order_prior(G_r, C_r)            # small bonus for aligning records
                                            # at similar positions in their
                                            # respective lists, since records
                                            # are typically emitted in document
                                            # order
```

Solve the maximum-weight one-to-one matching over `|G_records| × |C_records|` with the Hungarian algorithm. Pairs below threshold `τ_record = 0.3` are discarded.

After record alignment, every gold record is in one of:

- **Matched** — paired with a candidate record above `τ_record`.
- **Missing** — no candidate record above `τ_record` (false-negative record).

And every candidate record is either **Matched** or **Extra** (false-positive record). All node-level scoring (§§3.1–6) then runs **inside each matched record pair only**. Nodes belonging to a missing or extra record never enter the node-level alignment — they instead contribute to a record-level penalty (see §4 below).

`parent_id` pointers are by construction record-local, so structure_sim (§3.1) is well-defined inside each record pair.

### 3.1 Pairwise similarity

For every pair `(g, c)` of `(gold node, candidate node)` compute a similarity in `[0, 1]`:

```
sim(g, c) = 0.30 * type_match(g, c)        # 1 if same type, else 0
          + 0.50 * content_sim(g, c)       # see §5 per type
          + 0.20 * structure_sim(g, c)     # 1 if their parents are aligned
                                           #   to each other, else 0
```

`structure_sim` requires the alignment itself, so the procedure is iterative: solve the assignment with `structure_sim = 0`, then recompute with the resulting parent matches, then re-solve. Two passes converge in practice.

### 3.2 Assignment

Given the `|G| × |C|` similarity matrix, find the maximum-weight one-to-one matching between gold and candidate nodes (Hungarian algorithm; `scipy.optimize.linear_sum_assignment` works). Pairs whose similarity is below a threshold `τ = 0.4` are discarded — they are treated as "no good match exists" rather than being forced into a low-quality alignment.

### 3.3 Outcomes

After assignment each gold node is in exactly one of:

- **Matched** — paired with a candidate node above threshold.
- **Missing** — no candidate node above threshold (false negative).

Each candidate node is either:

- **Matched** — paired with a gold node.
- **Extra** — no gold node above threshold (false positive).

### 3.4 String normalization (used everywhere below)

Whenever two strings are compared in §3–§6:

1. `strip()` and collapse whitespace runs to single spaces.
2. Lowercase for comparison only (preserve original case in stored output).
3. Strip surrounding formatting punctuation (`:`, trailing `.`, smart quotes ↔ ASCII).
4. If both strings parse as numbers, compare numerically with tolerance `1e-6`.

These rules match `code_gen.md` §5.3 by design, so the two stages don't disagree about what "the same" means.

---

## 4. NodeMatchF1 — Do the Same Nodes Exist?

Treat node alignment as a retrieval problem, **aggregated across all matched record pairs**:

```
TP = number of matched node pairs (summed over all matched records)
FN = number of missing gold nodes
       = (gold nodes inside matched records that did not align)
       + (every node in a *missing* gold record)
FP = number of extra candidate nodes
       = (candidate nodes inside matched records that did not align)
       + (every node in an *extra* candidate record)

precision   = TP / (TP + FP)
recall      = TP / (TP + FN)
NodeMatchF1 = 2 * precision * recall / (precision + recall)
```

The aggregation rule above is what propagates record-level errors into the node-level score: nodes that belong to records the candidate failed to emit (or invented) all count against precision/recall, exactly as if the candidate had emitted those records but with zero node alignment.

A second flavor, **typed** Node F1, only counts a pair as a true positive if the type also matches. The eval report includes both: untyped (any aligned pair) and typed (aligned *and* same type). The headline `NodeMatchF1` uses the **typed** version, since two blocks of different types disagreeing about what something *is* is a real error.

A separate **`RecordMatchF1`** is also reported alongside, computed identically but at the record level — useful for diagnosing whether a low score is "bad records" or "bad nodes within good records". `RecordMatchF1` does **not** enter the headline `accuracy` formula in §2; `NodeMatchF1` already incorporates the record-level errors via the aggregation above. `RecordMatchF1` is purely diagnostic.

---

## 5. ContentScore — For Matched Nodes, Do Contents Agree?

For each matched pair `(g, c)` with the same type, compute a per-node content similarity `node_sim ∈ [0, 1]`. `ContentScore` is the **mean** over all type-matched pairs. Pairs with a type mismatch contribute `0`. Missing or extra nodes do *not* drag this down (they're already accounted for in `NodeMatchF1`).

### 5.1 `type = table`

Tables are scored as a combination of header agreement and cell agreement.

**Headers.** Treat headers as ordered lists; compute precision / recall / F1 over header strings (under §3.4 normalization), but penalize order disagreement: F1 is multiplied by `LCS(g_headers, c_headers) / max(|g_headers|, |c_headers|)`.

**Rows.** Rows are not ordered — alignment within a table matters more than position on the page. Align candidate rows to gold rows by maximum overlap on `{key: value}` agreement (Hungarian again, on a `|gold_rows| × |candidate_rows|` similarity matrix where row similarity is the fraction of shared `{key, value}` cells).

For each aligned row pair, compute cell F1 over `{key, value}` entries (a cell matches if both `key` and `value` match under §3.4). Unaligned gold rows count as recall misses; unaligned candidate rows count as precision misses.

```
table_sim = 0.30 * header_score + 0.70 * cell_F1
```

Cells dominate because that's the data; headers are mostly the schema.

### 5.2 `type = key_value`

Each block is a flat dict-like list. Score is precision / recall / F1 over `(key, value)` pairs (both must match under §3.4). Optionally, report a softer **key-only** F1 separately, so a block that has the right structure but wrong values is distinguishable from one with the wrong keys entirely.

```
kv_sim = F1 over matched (key, value) pairs
```

### 5.3 `type = metadata`

Metadata is a list of strings, treated as a multiset (order-insensitive by default).

```
metadata_sim = F1 over matched strings
```

If the gold marks a particular metadata block as order-sensitive (e.g. an ordered list of section titles), use sequence similarity instead (Levenshtein-normalized: `1 - editdistance / max(len_g, len_c)`).

### 5.4 Aggregation

```
ContentScore = mean( node_sim over type-matched pairs )
```

The eval report breaks this down per type (`ContentScore_table`, `ContentScore_kv`, `ContentScore_metadata`) since one stage may be much stronger than another at a particular block kind.

---

## 6. StructureScore — Do the Parent Edges Agree?

The relationship graph is what makes the output a *tree* rather than a flat list. A run that gets every node right but flattens the hierarchy is not equivalent to the gold.

Parent edges are scored **inside each matched record pair**, since `parent_id` is record-local by spec. Aggregation across record pairs is by total edge count (micro-average), not by mean of per-record rates.

For each matched gold node `g` with parent `g.parent`, find its aligned candidate `c` and `c.parent`. The edge agrees iff:

- `g.parent` is `null` and `c.parent` is `null`, **or**
- `g.parent` is matched to `c.parent` (i.e. they're the same node under the alignment within the same record pair).

```
edge_correct = number of matched gold nodes whose parent edge agrees
StructureScore = edge_correct / number_of_matched_gold_nodes
```

Optionally, also report a softer **path** score: for each pair of matched gold nodes, do they have the same ancestor relationship in the candidate tree (one is an ancestor of the other, or neither is)? This catches cases where the candidate gets the right *containment* even with an extra intermediate node.

The eval report includes the `note` field comparison too, but only as a **diagnostic** — a non-empty mismatch in `note` text contributes to a `note_agreement_rate` reported alongside `StructureScore`, not to the headline number, because `note` is free-form prose and unfair to grade strictly.

---

## 7. Output

For each evaluated comparison, write **two** files — one machine-readable, one human-readable:

```
results/
├── <doc_name>__<model>.eval.json   # structured score + diagnostics
└── <doc_name>__<model>.eval.txt    # plain-text mismatch analysis (see §7.2)
```

Both files cover the same eval run; `eval.txt` is generated *from* `eval.json` so the two can never disagree. The text file is what a human (or an LLM Author in stage 2) reads to understand *why* the score is below 1.0; the JSON is what tools consume.

### 7.1 `eval.json` — structured

Schema:

Because gold and candidate node `id`s are scoped to a record (`agent_data_extraction.md` §4.1), every diagnostic entry that mentions a node id also names the **record pair** it lives in. The convention is `{gold_record_id, candidate_record_id, gold_id, candidate_id}` — both record ids are included so an entry uniquely identifies its node even when both records use `n1` as a node id.

```json
{
  "doc_name": "...",
  "reference": "human" | "agent",
  "candidate": "agent" | "code",
  "exact_match": false,
  "accuracy": 0.873,
  "components": {
    "RecordMatchF1": { "typed_f1": 1.00, "precision": 1.00, "recall": 1.00 },
    "NodeMatchF1":   { "typed_f1": 0.92, "untyped_f1": 0.95, "precision": 0.93, "recall": 0.91 },
    "ContentScore":  {
      "overall": 0.86,
      "by_type": { "table": 0.81, "key_value": 0.94, "metadata": 0.88 }
    },
    "StructureScore": { "edge_accuracy": 0.84, "path_accuracy": 0.91, "note_agreement_rate": 0.62 }
  },
  "record_alignment": [
    { "gold_record_id": "r1", "candidate_record_id": "r1", "record_sim": 0.97 },
    { "gold_record_id": "r2", "candidate_record_id": "r2", "record_sim": 0.91 }
  ],
  "missing_gold_records":      [],
  "extra_candidate_records":   [],
  "alignment": [
    {
      "gold_record_id": "r1", "candidate_record_id": "r1",
      "gold_id": "n1", "candidate_id": "m4",
      "type_match": true, "content_sim": 0.93
    }
  ],
  "missing_gold_nodes": [
    { "gold_record_id": "r1", "gold_id": "n7", "type": "metadata" }
  ],
  "extra_candidate_nodes": [
    { "candidate_record_id": "r2", "candidate_id": "m9", "type": "table" }
  ],
  "content_diffs": [
    {
      "gold_record_id": "r1", "candidate_record_id": "r1",
      "gold_id": "n3", "candidate_id": "m1",
      "type": "table",
      "field": "rows[2].Discipline",
      "gold": "Suspension - 3 days",
      "candidate": "Suspension – 3 days"
    }
  ],
  "structure_diffs": [
    {
      "gold_record_id": "r1", "candidate_record_id": "r1",
      "gold_id": "n2", "gold_parent": "n1", "candidate_parent": null
    }
  ]
}
```

The `alignment`, `*_diffs`, and `missing/extra` lists are **diagnostics** — what to look at when the score is below 1.0. The single number a human should read first is `accuracy`.

### 7.2 `eval.txt` — human-readable mismatch analysis

Alongside `eval.json`, the evaluator emits a plain-text report that **walks through every mismatch and explains, in natural language, why it is a mismatch**. The goal is that a person (or the stage-2 Author agent) can read this top-to-bottom and immediately understand what's wrong without cross-referencing the JSON.

Required structure (in this order):

1. **Header** — one line each: doc name, reference vs candidate roles, model name(s), final `accuracy`, `exact_match` flag, the configured threshold (if known), and a one-sentence verdict (`PASS` / `FAIL` / `BORDERLINE`).
2. **Score breakdown** — the four component scores from §2 (`RecordMatchF1`, `NodeMatchF1`, `ContentScore`, `StructureScore`) with their sub-scores, formatted as a small table.
3. **Record-level summary** — one line per matched record pair (`r1↔r1: sim=0.97, accuracy=0.91`), plus separate lists of *missing gold records* and *extra candidate records*. This sits above the per-node sections so the reader can see at a glance whether the problem is records or content.
4. **Mismatch sections**, one per category, in this order: *Missing nodes*, *Extra (hallucinated) nodes*, *Type mismatches*, *Content mismatches*, *Structure mismatches*. Mismatches are **grouped by record pair**, with a sub-heading like `--- record r1 ↔ r1 ---` introducing each group. Each entry within a group includes:
   - **What** — the gold value vs the candidate value, quoted verbatim (no normalization applied to the displayed text).
   - **Where** — the (gold record id, gold node id) pair, the (candidate record id, candidate node id) pair if any, and the exact field path (e.g. `rows[2].Discipline`, `headers[3]`, `parent_id`).
   - **Why it counted as a mismatch** — a short, mechanical explanation referencing the rule that fired. The explanation must name the specific rule (see §7.3 for the catalog of reasons).
   - **Suggested fix** *(optional but recommended)* — a one-line hint for what would resolve it (e.g. *"normalize en-dash to hyphen before emitting"*, *"the candidate is parsing this row as metadata; emit it as `key_value`"*).
5. **Summary of root causes** — a short paragraph that groups the individual mismatches by likely cause (e.g. "9 of 14 content mismatches are en-dash vs hyphen normalization; 3 are off-by-one column shifts in the second table; the missing record r3 cost 6 nodes by itself"). This is the most useful section for fast iteration.

Example (abridged):

```
=== EVAL REPORT =========================================================
doc:        Investigations_Redacted
reference:  agent (claude-sonnet-4-6)
candidate:  code (code-extractor)
threshold:  0.90
accuracy:   0.873      exact_match: False     verdict: BORDERLINE

--- Score breakdown ----------------------------------------------------
RecordMatchF1   typed=1.00  P=1.00  R=1.00      (records aligned cleanly)
NodeMatchF1     typed=0.92  untyped=0.95  P=0.93  R=0.91
ContentScore    overall=0.86   table=0.81  key_value=0.94  metadata=0.88
StructureScore  edge=0.84  path=0.91  note_agreement=0.62

--- Records ------------------------------------------------------------
matched: r1 ↔ r1 (sim=0.97, node_acc=0.94)
matched: r2 ↔ r2 (sim=0.91, node_acc=0.83)
missing gold records:    (none)
extra candidate records: (none)

--- Missing nodes (1) --------------------------------------------------
--- record r2 ↔ r2 ---
[gold r2/n7 / metadata]
  what:  ["Confidentiality Notice — internal use only"]
  where: top-level metadata block on page 3
  why:   no candidate node aligned to this gold node above τ=0.4
         (closest candidate similarity = 0.21).
  fix:   the extractor isn't emitting page-level banners; add a pass
         that captures lines above the first table on each page.

--- Content mismatches (3) ---------------------------------------------
--- record r1 ↔ r1 ---
[gold r1/n3 / table / rows[2].Discipline]
  gold:        "Suspension - 3 days"
  candidate:   "Suspension – 3 days"
  why:         strings differ after §3.4 normalization step 4
               (en-dash U+2013 not folded to ASCII hyphen).
  fix:         normalize hyphen-like characters before emitting cells.

[gold r1/n3 / table / headers[2]]
  gold:        "Discipline"
  candidate:   "Disposition"
  why:         header strings differ; column appears shifted left by one
               (candidate's "Disposition" sits where gold's "Discipline" is,
               and candidate is missing a header at index 1).
  fix:         re-detect column boundaries; the third column header text
               likely got merged with the second.

[gold r1/n5 / key_value / Investigator]
  gold:        "Sgt. J. Doe"
  candidate:   "Sgt . J . Doe"
  why:         differs after §3.4 (extra spaces around periods survive
               whitespace collapse because the periods aren't stripped
               internally — only trailing punctuation is).
  fix:         tighten whitespace around interior punctuation in extractor.

--- Structure mismatches (1) -------------------------------------------
--- record r1 ↔ r1 ---
[gold r1/n2 / key_value]
  gold parent:      r1/n1 (metadata, "Internal Investigation Report")
  candidate parent: null
  why:              candidate emitted n2 as a top-level node; gold has it
                    nested under the report-title metadata banner.
  fix:              attach key_value blocks immediately following a
                    metadata banner to that banner as parent.

--- Summary of root causes --------------------------------------------
- 2 of 3 content mismatches stem from incomplete §3.4 normalization
  (en-dash, interior whitespace around punctuation).
- 1 content mismatch and the structure mismatch reflect a column-
  detection bug in the second table (header shift propagates into rows).
- The missing metadata node suggests the extractor doesn't model
  page-level banners at all.
========================================================================
```

Formatting rules:

- Plain ASCII text with section dividers (no markdown, no ANSI). The file is meant to be readable in a terminal, an editor, and inside an LLM prompt without any rendering.
- Quote string values verbatim with surrounding double quotes; do not normalize them in the displayed text (so the reader can *see* the en-dash vs hyphen).
- Numbers are formatted to 2–3 significant digits.
- Each mismatch entry is at most ~6 lines; long table cells should be truncated with `…` after 80 chars and a marker noting the truncation.
- The file ends with a single `===` rule and a newline.

### 7.3 Catalog of mismatch reasons

The "why" line in each mismatch entry must name one of the following canonical reasons, so the text is uniform and machine-greppable. Add to this list as new failure modes are observed.

| Reason code              | Human label                                       |
|--------------------------|---------------------------------------------------|
| `R-RECORD-MISSING`       | gold record has no candidate counterpart above τ_record (nodes inside it count as missing) |
| `R-RECORD-EXTRA`         | candidate record has no gold counterpart above τ_record (nodes inside it count as extra) |
| `R-NODE-UNALIGNED`       | no candidate node aligned to this gold node above τ (within a matched record pair) |
| `R-NODE-EXTRA`           | candidate node has no gold counterpart above τ (within a matched record pair) |
| `R-TYPE-MISMATCH`        | aligned pair has different `type`                 |
| `R-HEADER-DIFFERS`       | table header strings differ after §3.4            |
| `R-HEADER-ORDER`         | table headers are the same set but in different order |
| `R-ROW-MISSING`          | gold row has no aligned candidate row             |
| `R-ROW-EXTRA`            | candidate row has no aligned gold row             |
| `R-CELL-DIFFERS`         | aligned cell values differ after §3.4             |
| `R-KV-KEY-MISSING`       | key_value: key present in gold, absent in candidate |
| `R-KV-KEY-EXTRA`         | key_value: key present in candidate, absent in gold |
| `R-KV-VALUE-DIFFERS`     | key_value: shared key but values differ after §3.4 |
| `R-METADATA-STRING-MISSING` | metadata: string present in gold, absent in candidate |
| `R-METADATA-STRING-EXTRA`   | metadata: string present in candidate, absent in gold |
| `R-PARENT-DIFFERS`       | aligned node has a different parent under the alignment |
| `R-NORMALIZATION-RESIDUAL` | strings differ only because §3.4 didn't fold a particular character class (en-dash, smart quotes, NBSP, …) — usually a bug in the extractor, not in the gold |

The reason code is included in the JSON `*_diffs` entries (as a `"reason"` field) and surfaced verbatim in the text report, so the two views always agree.

### 7.4 Multi-document roll-up

When evaluating multiple documents, also write a roll-up:

```
results/
└── eval_summary__<model>.json
```

with per-doc `accuracy` plus macro / micro means across the set.

---

## 8. Reporting & Sanity Checks

Alongside the numeric score, the eval report should make it easy to spot common failure modes:

- **Type confusion.** Count of `(gold_type → candidate_type)` reassignments. A spike in `key_value → metadata` usually means the candidate is failing to recognize form fields.
- **Schema drift.** For tables, list any header strings present in gold but missing in candidate (and vice versa). Renamed columns are by far the most common subtle error.
- **Hallucinated content.** Extra candidate nodes whose content does not appear anywhere in the source PDF text. (Optional check: requires running `pdftotext` on the sample and grepping.)
- **Determinism.** Re-run the candidate twice on the same input; flag any change. Stage-1 (agent) output may legitimately vary; stage-2 (code) output should not.

---

## 9. Suggested Project Layout

Building on the layouts from the previous two docs:

```
twix2.0/
├── docs/
│   ├── agent_data_extraction.md
│   ├── code_gen.md
│   └── eval.md                   # this file
├── results/                      # stage 1 + stage 2 outputs + .eval.json files
└── src/
    ├── data_extraction/          # stage 1
    ├── code_gen/                 # stage 2
    └── eval/                     # stage 3
        ├── normalize.py          # §3.4 string normalization
        ├── align.py              # §3 node alignment (Hungarian)
        ├── content.py            # §5 per-type content similarity
        ├── structure.py          # §6 parent-edge scoring
        ├── score.py              # combines into the headline accuracy + reason-tagged diffs
        ├── render.py             # §7.2 — turns eval.json into eval.txt
        └── run.py                # CLI: pick a doc, pick reference + candidate, write eval.json + eval.txt
```

---

## 10. Validation Checklist

Before trusting an eval number:

1. Both inputs parse and pass the stage-1 schema validation (`agent_data_extraction.md` §7), including the record-level checks (records non-empty, record_ids unique, parent_ids record-local).
2. The reference is identified explicitly (`human` or `agent`) — no implicit defaults that could swap silently between docs.
3. `accuracy ∈ [0, 1]` and equals the weighted sum of components in §2 to within `1e-9`.
4. `exact_match == True` ⇔ all of: `NodeMatchF1 == 1`, `ContentScore == 1`, `StructureScore == 1` (and, by construction, `RecordMatchF1 == 1`, since record errors propagate into `NodeMatchF1`).
5. Re-running eval on the same two inputs is deterministic (alignment ties are broken first by record_id order, then by node id order).
6. Every diagnostic entry in `eval.json` carries both `gold_record_id` and `candidate_record_id` (or, for missing/extra records, just one of the two). No entry references a node id without naming the record it belongs to.
7. Both `eval.json` and `eval.txt` are emitted; every mismatch in the JSON's `*_diffs` lists appears in the text report, and every entry in the text report has a `reason` code from §7.3 that matches the JSON.
8. Spot-check at least one mismatch from `content_diffs` against the source PDF — graders are not infallible, and a "wrong" answer is sometimes the gold being wrong.
