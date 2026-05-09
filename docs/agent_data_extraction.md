# Agent-Based Data Extraction

This document specifies the **first stage** of the pipeline: extracting a structured, tree-shaped representation of the data contained in a PDF document by prompting an LLM agent on a small sample of pages.

The goal of this stage is **not** to extract every record in the document. It is to produce a faithful *representation* of the data — i.e. a schema-like tree describing what blocks of data exist, what type each block is, and how the blocks relate to one another. Downstream stages will use that representation to drive full-document extraction.

---

## 1. Pipeline Overview

```
PDF (any size)
   │
   ├── Step 1: Sample first 5 pages  ──►  sample.pdf
   │
   ├── Step 2: Build prompt with template hint
   │
   ├── Step 3: Call extraction agent
   │
   └── Output: data representation tree (JSON)
                 │
                 └── saved to  results/<doc_name>__<model>.json
```

---

## 2. Step 1 — Sample Data

For *any* input PDF, take the **first 5 pages** as the sample document. If the PDF has fewer than 5 pages, take all available pages.

- Input: a PDF file at `<pdf_path>`.
- Output: a sampled PDF (or the equivalent in-memory pages) containing pages 1–5.
- The sample is what gets fed to the agent in Step 3. The full PDF is **not** sent to the agent at this stage.

Recommended implementation: use `pypdf` (or `pdfplumber`) to slice the first 5 pages into a temporary PDF, or to pass page-rendered images to a multimodal model.

---

## 3. Step 2 — Template Hint

When the agent is prompted, the prompt **must** include the following hint (or a paraphrase of it):

> Many of the records / pages in this sample are likely generated from the **same template**. They therefore share a large amount of common fields, common headers, and common structural layout. Identify the **record boundary** in the document — the unit that repeats — and emit the output as a list of records, each containing the same kind of nodes. Within a single record, do not duplicate structure that is purely template overhead; capture each record's actual *values*. Records that look structurally identical (same set of node types, same headers, same key labels) are evidence the boundary is correct.

The purpose of this hint is two-fold: (a) bias the agent toward recognizing the repeating template unit rather than treating the document as an unstructured stream, and (b) ensure the JSON's top level is a list of records (see §4.1), so downstream stages can process each record independently.

---

## 4. Step 3 — Agent Call & Output Format

The agent is asked to read the sample PDF and return a single JSON object that describes the data as a **tree**. Each node in the tree corresponds to a **data block** observed in the document.

### 4.1 Top-level JSON shape

The top level of the JSON is a **list of records**. Each record contains its own list of nodes describing the data blocks that belong to that record. A document is a sequence of records — possibly only one — that share an underlying template:

```json
{
  "doc_name": "<basename of source pdf, no extension>",
  "model": "<model identifier used to produce this output>",
  "sampled_pages": 5,
  "records": [
    {
      "record_id": "<stable string id, e.g. r1, r2, ...>",
      "nodes": [
        { ... node ... },
        { ... node ... }
      ]
    },
    {
      "record_id": "r2",
      "nodes": [ ... ]
    }
  ]
}
```

Rules:

- `records` is **always** a list, even when there is exactly one record. A single-record document is `"records": [ { "record_id": "r1", "nodes": [...] } ]`.
- Every record has a `record_id` that is unique within the JSON. Record ids are arbitrary strings; `r1`, `r2`, ... is the recommended convention. The order of records in the list is the order they appear in the document.
- `nodes` inside a record is a flat list. Tree structure is encoded via each node's `relationship.parent_id` pointer (see §4.2), not by physical nesting.
- **Node ids are unique within a record** but need not be globally unique across records. Two records can both have a node `n1`; they refer to different blocks.
- **`relationship.parent_id` only refers to nodes in the same record.** Cross-record relationships are not allowed: records are conceptually independent instances of the same template, and downstream stages process them independently.
- A node with no parent (top-level block within its record) has `relationship.parent_id = null`.

Record-boundary guidance for the agent: a record corresponds to one instance of the repeating template (e.g. one case, one incident, one officer profile). When in doubt, prefer **more records with simpler trees** over one giant record with deeply nested duplication. If the document genuinely has no repeating structure, emit a single record containing everything.

### 4.2 Node schema

Every node has **exactly three semantic fields** (plus an `id`):

```json
{
  "id": "<stable string id, e.g. n1, n2, ...>",
  "type": "table" | "key_value" | "metadata",
  "content": <see per-type spec below>,
  "relationship": {
    "parent_id": "<id of parent node, or null>",
    "note": "<short string describing the association>"
  }
}
```

#### `type`

One of three values:

- `table` — a tabular block with a header row and data rows.
- `key_value` — a block of one or more key/value pairs (form-style: e.g. `Name: John`, `DOB: 1990-01-01`).
- `metadata` — anything that is neither a table nor a clean key/value block: page headers/footers, titles, free-text labels, disclaimers, section banners, etc.

#### `content` per type

- **`type = "table"`**

  ```json
  "content": {
    "headers": ["Header A", "Header B", "Header C"],
    "rows": [
      [
        {"key": "Header A", "value": "..."},
        {"key": "Header B", "value": "..."},
        {"key": "Header C", "value": "..."}
      ],
      [ ... next row ... ]
    ]
  }
  ```

  Each row is a list of `{key, value}` pairs where `key` is the corresponding column header and `value` is the cell text. Row length should match `headers` length.

- **`type = "key_value"`**

  ```json
  "content": [
    {"key": "Officer Name", "value": "..."},
    {"key": "Badge Number", "value": "..."}
  ]
  ```

- **`type = "metadata"`**

  ```json
  "content": [
    "Page header text",
    "Confidentiality notice",
    "Section title: Use of Force Report"
  ]
  ```

#### `relationship`

Used when the current node is **semantically associated with or nested under** another node. Examples:

- A `key_value` block giving demographic info about a person whose name is one of the rows of a table → its parent is that table, and the `note` should pinpoint the row/field (e.g. `"belongs to row where Officer Name = ..."` or `"associated with the 'Subject' column of the Incidents table"`).
- A sub-table that appears underneath, and elaborates on, a particular field of a parent key/value block → its parent is that key/value block, with `note` identifying the field.
- A `metadata` banner that scopes a table beneath it → the table's parent is the metadata node (or vice versa, depending on which is the conceptual container — pick the more natural one and explain in `note`).

If there is no association, `parent_id` is `null` and `note` is `""`.

### 4.3 Full example

A two-record document where each record describes one investigation case. Both records share the same template (banner → case fields → allegations table), so they have the same node types in the same order; only the values differ.

```json
{
  "doc_name": "Investigations_Redacted",
  "model": "claude-sonnet-4-6",
  "sampled_pages": 5,
  "records": [
    {
      "record_id": "r1",
      "nodes": [
        {
          "id": "n1",
          "type": "metadata",
          "content": ["Champaign Police Department", "Internal Investigation Report"],
          "relationship": {"parent_id": null, "note": ""}
        },
        {
          "id": "n2",
          "type": "key_value",
          "content": [
            {"key": "Case Number", "value": "2021-014"},
            {"key": "Date Opened", "value": "2021-03-12"},
            {"key": "Investigator", "value": "..."}
          ],
          "relationship": {"parent_id": "n1", "note": "case-level metadata for the report named in n1"}
        },
        {
          "id": "n3",
          "type": "table",
          "content": {
            "headers": ["Allegation", "Disposition", "Discipline"],
            "rows": [
              [
                {"key": "Allegation",  "value": "Excessive Force"},
                {"key": "Disposition", "value": "Sustained"},
                {"key": "Discipline",  "value": "Suspension - 3 days"}
              ]
            ]
          },
          "relationship": {"parent_id": "n2", "note": "allegations table belonging to the case identified by Case Number in n2"}
        }
      ]
    },
    {
      "record_id": "r2",
      "nodes": [
        {
          "id": "n1",
          "type": "metadata",
          "content": ["Champaign Police Department", "Internal Investigation Report"],
          "relationship": {"parent_id": null, "note": ""}
        },
        {
          "id": "n2",
          "type": "key_value",
          "content": [
            {"key": "Case Number", "value": "2021-022"},
            {"key": "Date Opened", "value": "2021-05-08"},
            {"key": "Investigator", "value": "..."}
          ],
          "relationship": {"parent_id": "n1", "note": "case-level metadata for the report named in n1"}
        },
        {
          "id": "n3",
          "type": "table",
          "content": {
            "headers": ["Allegation", "Disposition", "Discipline"],
            "rows": [
              [
                {"key": "Allegation",  "value": "Improper Search"},
                {"key": "Disposition", "value": "Not Sustained"},
                {"key": "Discipline",  "value": "None"}
              ]
            ]
          },
          "relationship": {"parent_id": "n2", "note": "allegations table belonging to the case identified by Case Number in n2"}
        }
      ]
    }
  ]
}
```

Note how `n1`, `n2`, `n3` are reused as ids inside both records — that's expected, because node ids are scoped to the record. `parent_id` pointers stay inside the same record (no cross-record edges).

---

## 5. Output Naming & Storage

Save the agent's JSON output to:

```
results/<doc_name>__<model>.json
```

Where:

- `<doc_name>` is the source PDF filename without the `.pdf` extension (preserve underscores, but replace path separators and spaces with `_`).
- `<model>` is the model identifier used (e.g. `claude-sonnet-4-6`, `claude-opus-4-6`, `gpt-4o`, etc.). Use a filesystem-safe form (replace `/` and spaces with `-`).
- The two are joined by a **double underscore** `__` so the doc name and model can be split unambiguously.

Examples:

- `results/Investigations_Redacted__claude-sonnet-4-6.json`
- `results/22-274.releasable__claude-opus-4-6.json`
- `results/id_18_28_45_48_51_57_60_70_72_79_81_89_91_92_94_95_97_99_102_105_113_117_118_119_122_125_131_132_137_139_150_v1__gpt-4o.json`

The `results/` folder lives under the repository root. Create it if it does not exist.

---

## 6. Suggested Project Layout

```
twix2.0/
├── data/                        # source PDFs (already exists)
├── docs/
│   └── agent_data_extraction.md # this file
├── results/                     # agent JSON outputs land here
└── src/                         # implementation (to be added)
    └── data_extraction/
        ├── sample_pdf.py        # Step 1: first-N-page sampler
        ├── prompt.py            # Step 2: prompt + template hint
        ├── agent.py             # Step 3: call the model
        └── run.py               # ties it all together, writes results/
```

---

## 7. Validation Checklist

Before accepting an agent's output, verify:

1. The JSON parses.
2. `records` is a non-empty list. Each record has a `record_id` (string) and a `nodes` list.
3. `record_id` values are unique within the JSON.
4. Within each record, `nodes` is a non-empty list, and every node has `id`, `type`, `content`, `relationship`.
5. Within each record, node `id` values are unique (uniqueness is *per record*, not global).
6. `type` is one of `table`, `key_value`, `metadata`.
7. For `table` nodes: every row's length equals `len(headers)`, and every row entry's `key` matches the corresponding header.
8. For `key_value` nodes: `content` is a list of `{key, value}` objects.
9. For `metadata` nodes: `content` is a list of strings.
10. Every `relationship.parent_id` is either `null` or refers to an existing node `id` **in the same record** — no dangling pointers, no cycles, no cross-record edges.
11. Output filename follows `<doc_name>__<model>.json` and lives under `results/`.
