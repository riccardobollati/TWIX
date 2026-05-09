"""Stage 1 step 2 — build the extraction prompt.

agent_data_extraction.md §3 mandates the template-hint paragraph. §4 defines
the records-based JSON shape we ask the agent to return.
"""

from __future__ import annotations


TEMPLATE_HINT = (
    "Many of the records / pages in this sample are likely generated from the "
    "SAME TEMPLATE. They therefore share a large amount of common fields, common "
    "headers, and common structural layout. Identify the **record boundary** in the "
    "document — the unit that repeats — and emit the output as a list of records, "
    "each containing the same kind of nodes. Within a single record, do not duplicate "
    "structure that is purely template overhead; capture each record's actual values. "
    "Records that look structurally identical (same set of node types, same headers, "
    "same key labels) are evidence the boundary is correct."
)


SCHEMA_INSTRUCTIONS = """\
Return a single JSON object that describes the data in the sampled PDF as a list
of records, where each record is one instance of the repeating template unit.

Top-level shape:
{
  "doc_name": "<basename of source pdf, no extension>",
  "model": "<model identifier (we will set this to the calling model)>",
  "sampled_pages": <integer = number of sampled pages>,
  "records": [
    {
      "record_id": "<stable string id, e.g. r1, r2, ...>",
      "nodes": [ ...node... ]
    },
    ...
  ]
}

Rules for records:
- "records" is ALWAYS a list, even when there is exactly one record.
- Every record has a unique "record_id" string (r1, r2, ... is recommended).
- Within a record, "nodes" is a flat list. Tree structure is encoded via each
  node's relationship.parent_id pointer, not by physical nesting.
- Node ids are unique WITHIN a record but may repeat across records (e.g. both
  r1 and r2 may have a node "n1" — that is expected and correct).
- relationship.parent_id only refers to nodes in THE SAME RECORD. No cross-
  record edges allowed.
- A node with no parent has relationship.parent_id = null.

Each node has exactly four fields:
{
  "id": "<stable string id like n1, n2, n3, ...>",
  "type": "table" | "key_value" | "metadata",
  "content": <see below>,
  "relationship": {
    "parent_id": "<id of parent node in the same record, or null>",
    "note": "<short description of the association, '' if no parent>"
  }
}

Per-type content:

(1) type = "table"
    "content": {
      "headers": ["Header A", "Header B", "Header C"],
      "rows": [
        [
          {"key": "Header A", "value": "..."},
          {"key": "Header B", "value": "..."},
          {"key": "Header C", "value": "..."}
        ],
        [ ...next row... ]
      ]
    }
  Each row's length must equal headers' length. Each row entry's key must be
  the corresponding header.

(2) type = "key_value"
    "content": [
      {"key": "Officer Name", "value": "..."},
      {"key": "Badge Number", "value": "..."}
    ]

(3) type = "metadata"
    "content": [
      "Page header text",
      "Confidentiality notice",
      "Section title: Use of Force Report"
    ]

Relationship rules:
- parent_id refers to another node id in the SAME record, or null.
- No dangling pointers. No cycles. No cross-record edges.
- Use parent_id when the node is conceptually nested under or scoped by another
  node within the same record. Otherwise parent_id is null and note is "".

Validation rules to obey:
1. JSON parses.
2. "records" is a non-empty list. Each record has "record_id" (string) and a
   "nodes" list.
3. "record_id" values are unique across all records in the JSON.
4. Within each record, "nodes" is non-empty and every node has id, type,
   content, relationship.
5. Within each record, node "id" values are unique (per-record uniqueness;
   the same id may appear in different records).
6. type is one of {table, key_value, metadata}.
7. table rows length == len(headers); each row entry's key matches the header.
8. key_value content is a list of {key, value} objects.
9. metadata content is a list of strings.
10. Every relationship.parent_id is null or refers to an existing node id IN
    THE SAME RECORD; no dangling pointers, no cycles, no cross-record edges.
"""


def build_prompt(
    doc_name: str,
    model_id: str,
    n_sampled_pages: int,
    sample_pdf_path: str,
    output_json_path: str,
    schema_errors_from_prior_attempt: list[str] | None = None,
) -> str:
    """Build the extraction prompt that instructs the agent to read the PDF and emit JSON."""
    error_block = ""
    if schema_errors_from_prior_attempt:
        bullets = "\n".join(f"  - {e}" for e in schema_errors_from_prior_attempt)
        error_block = (
            "\nYour PREVIOUS attempt failed schema validation with these errors:\n"
            f"{bullets}\n"
            "Fix every one of those errors in this new attempt.\n"
        )

    return f"""\
You are a data-extraction agent. Read the sampled PDF at the path below and
produce a structured JSON describing its data as a list of records.

INPUT
  Sampled PDF path:            {sample_pdf_path}
  Number of sampled pages:     {n_sampled_pages}
  Document name (for output):  {doc_name}
  Model identifier (for output JSON):  {model_id}
  Output JSON path (write here): {output_json_path}

TEMPLATE HINT (REQUIRED CONTEXT — read carefully):
{TEMPLATE_HINT}

OUTPUT FORMAT
{SCHEMA_INSTRUCTIONS}

{error_block}
INSTRUCTIONS
1. Open and read the sampled PDF at the path above. Inspect every page.
2. Identify the record boundary — the repeating unit (e.g. one case, one
   incident, one officer profile). Use the template hint to guide this.
3. For each record, identify the data blocks (tables, key/value blocks,
   metadata) and construct the nodes list. Use ids n1, n2, n3 ... within
   each record.
4. Emit one entry in "records" per record, with record_ids r1, r2, r3 ... in
   document order. If the document has no repeating structure, emit a single
   record r1 containing all nodes.
5. Set "doc_name" to {doc_name!r}, "model" to {model_id!r}, "sampled_pages"
   to {n_sampled_pages}.
6. Write the final JSON object to the output path above using the Write tool.
   Do NOT write anything else to that path. Do NOT print the JSON to stdout
   (the JSON belongs in the file). Print only a brief one-line confirmation
   such as "wrote <path>".
7. Validate the JSON before writing: it must satisfy every validation rule
   above. If you find an error, fix it and rewrite the file.

Begin now.
"""
