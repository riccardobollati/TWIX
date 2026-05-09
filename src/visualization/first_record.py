"""visualization.md §3 — extract the first record from a parsed JSON tree."""

from __future__ import annotations


def select_first_record(data: dict) -> dict:
    """Return metadata about the first record in the JSON tree.

    Returns a dict with:
      error:       str | None
      nodes:       list of node dicts (first record's nodes)
      record_id:   str | None
      n_records:   int
      doc_name:    str
      model:       str
      sampled_pages: int
    """
    records = data.get("records") or []
    n_records = len(records)
    doc_name = data.get("doc_name", "")
    model = data.get("model", "")
    sampled_pages = int(data.get("sampled_pages", 0))

    if n_records == 0:
        return {
            "error": "No records in input JSON — nothing to render.",
            "nodes": [],
            "record_id": None,
            "n_records": 0,
            "doc_name": doc_name,
            "model": model,
            "sampled_pages": sampled_pages,
        }

    first = records[0]
    return {
        "error": None,
        "nodes": list(first.get("nodes") or []),
        "record_id": first.get("record_id"),
        "n_records": n_records,
        "doc_name": doc_name,
        "model": model,
        "sampled_pages": sampled_pages,
    }
