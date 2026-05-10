"""Extractor for Investigations_Redacted (Champaign PD Complaints Detail Rpt #A-2).

Layout-aware parser using pdfplumber word coordinates. Each page contains
multiple "case" records; each record has:
  - Case info (key_value)
  - Complainant info (key_value, child of case info)
  - Complaints table (table, child of case info)
  - Officers table (table, child of case info)

The first record of the document also gets a metadata node with the page banner
and footer strings.
"""

import os
import re

import pdfplumber


# --- Section header detectors ---------------------------------------------

CASE_HEADER_RE = re.compile(r"^Date\s+Number\s+Investigator")
COMPLAINANT_RE = re.compile(r"^Complainant:")
COMPLAINT_HEADER_RE = re.compile(r"^Type\s+Of\s+Complaint")
OFFICER_HEADER_RE = re.compile(r"^Name\s+ID\s+No\.")
OFFICER_ROW_RE = re.compile(r"^Officer\s+#:")


# --- Schemas --------------------------------------------------------------

CASE_INFO_KEYS = [
    "Date",
    "Number",
    "Investigator",
    "Date Assigned",
    "Racial",
    "Category / Type",
    "Location Of Occurrence",
    "Disposition",
    "Completed",
    "Recorded On Camera",
    "Body Cam Status",
]

COMPLAINANT_KEYS = ["Complainant", "DOB", "Gender", "Address", "H Phone"]

COMPLAINT_HEADERS = [
    "Complaint #",
    "Type Of Complaint",
    "Description",
    "Complaint Disposition",
]

OFFICER_HEADERS = [
    "Officer #",
    "Name",
    "ID No.",
    "Rank",
    "Division",
    "Officer Disposition",
    "Action Taken",
    "Body Cam",
]


# --- Column boundary helpers (x-coordinates determined empirically) -------

def _assign_case_col(x: float) -> str:
    if x < 100:
        return "Date"
    if x < 160:
        return "Number"
    if x < 220:
        return "Investigator"
    if x < 282:
        return "Date Assigned"
    if x < 310:
        return "Racial"
    if x < 400:
        return "Category / Type"
    if x < 580:
        return "Location Of Occurrence"
    if x < 635:
        return "Disposition"
    if x < 678:
        return "Completed"
    if x < 705:
        return "Body Cam Status"
    return "Recorded On Camera"


def _assign_complaint_col(x: float) -> str:
    if x < 220:
        return "Complaint #"
    if x < 460:
        return "Type Of Complaint"
    if x < 620:
        return "Description"
    return "Complaint Disposition"


def _assign_officer_col(x: float) -> str:
    if x < 220:
        return "Officer #"
    if x < 360:
        return "Name"
    if x < 405:
        return "ID No."
    if x < 480:
        return "Rank"
    if x < 545:
        return "Division"
    if x < 635:
        return "Officer Disposition"
    if x < 710:
        return "Action Taken"
    return "Body Cam"


# Approximate x-bounds for complainant value regions (between labels).
COMPLAINANT_BOUNDS = {
    "Complainant": (115, 240),
    "DOB": (270, 317),
    "Gender": (345, 387),
    "Address": (440, 660),
    "H Phone": (700, 10000),
}
COMPLAINANT_LABEL_TEXTS = {"Complainant:", "DOB:", "Gender:", "Address:", "H", "Phone:"}


# --- Generic helpers ------------------------------------------------------

def _group_lines(words, y_tol: float = 3.0):
    """Group words into lines by y-coordinate proximity.

    Returns a list of dicts with keys: top, words (x-sorted), text.
    """
    if not words:
        return []
    sorted_words = sorted(words, key=lambda w: (w["top"], w["x0"]))
    lines = []
    current = [sorted_words[0]]
    anchor_y = sorted_words[0]["top"]
    for w in sorted_words[1:]:
        if abs(w["top"] - anchor_y) <= y_tol:
            current.append(w)
        else:
            current.sort(key=lambda x: x["x0"])
            lines.append({
                "top": sum(x["top"] for x in current) / len(current),
                "words": current,
                "text": " ".join(x["text"] for x in current),
            })
            current = [w]
            anchor_y = w["top"]
    current.sort(key=lambda x: x["x0"])
    lines.append({
        "top": sum(x["top"] for x in current) / len(current),
        "words": current,
        "text": " ".join(x["text"] for x in current),
    })
    return lines


def _bucket_words(words, assign_fn, keys):
    """Group words by column key; words within a bucket are kept in (y, x) order."""
    buckets = {k: [] for k in keys}
    for w in words:
        col = assign_fn(w["x0"])
        if col in buckets:
            buckets[col].append(w)
    for k in buckets:
        buckets[k].sort(key=lambda w: (w["top"], w["x0"]))
    return buckets


def _join(words):
    return " ".join(w["text"] for w in words).strip()


# --- Section parsers ------------------------------------------------------

def _parse_case_info(words):
    buckets = _bucket_words(words, _assign_case_col, CASE_INFO_KEYS)
    return [{"key": k, "value": _join(buckets[k])} for k in CASE_INFO_KEYS]


def _parse_complainant(words):
    buckets = {k: [] for k in COMPLAINANT_KEYS}
    for w in words:
        if w["text"] in COMPLAINANT_LABEL_TEXTS:
            continue
        x = w["x0"]
        for k, (lo, hi) in COMPLAINANT_BOUNDS.items():
            if lo <= x < hi:
                buckets[k].append(w)
                break
    for k in buckets:
        buckets[k].sort(key=lambda w: (w["top"], w["x0"]))
    return [{"key": k, "value": _join(buckets[k])} for k in COMPLAINANT_KEYS]


def _parse_indexed_row(words, assign_fn, keys, index_key):
    """Parse a row whose first column has form 'Label #:N'."""
    buckets = _bucket_words(words, assign_fn, keys)
    row = []
    for k in keys:
        if k == index_key:
            text = _join(buckets[k])
            m = re.search(r"#:(\S+)", text)
            value = m.group(1) if m else text
        else:
            value = _join(buckets[k])
        row.append({"key": k, "value": value})
    return row


def _parse_complaint_row(words):
    return _parse_indexed_row(words, _assign_complaint_col, COMPLAINT_HEADERS, "Complaint #")


def _parse_officer_row(words):
    return _parse_indexed_row(words, _assign_officer_col, OFFICER_HEADERS, "Officer #")


# --- Metadata -------------------------------------------------------------

def _build_metadata(lines):
    """Collect known banner/footer strings in the gold-specified order."""
    report_criteria = None
    champaign_pd = None
    complaints_by_date = None
    complaints_detail = None
    lea_line = None

    for line in lines:
        text = line["text"]
        if text.startswith("Report Criteria"):
            report_criteria = text
        elif text == "Complaints By Date":
            complaints_by_date = text
        elif text.startswith("L.E.A."):
            lea_line = text
        elif "Champaign" in text and "Police" in text and "Department" in text:
            left = [w for w in line["words"] if w["x0"] < 250]
            right = [w for w in line["words"] if w["x0"] >= 250]
            if left:
                complaints_detail = " ".join(w["text"] for w in left)
            if right:
                champaign_pd = " ".join(w["text"] for w in right)

    out = []
    for s in (report_criteria, champaign_pd, complaints_by_date, complaints_detail, lea_line):
        if s:
            out.append(s)
    return out


# --- Record assembly ------------------------------------------------------

def _parse_records_on_page(lines):
    """Return list of parsed record dicts (raw, before node id assignment)."""
    case_starts = [i for i, l in enumerate(lines) if CASE_HEADER_RE.match(l["text"])]
    complainant_idxs = [i for i, l in enumerate(lines) if COMPLAINANT_RE.match(l["text"])]
    complaint_hdr_idxs = [i for i, l in enumerate(lines) if COMPLAINT_HEADER_RE.match(l["text"])]
    officer_hdr_idxs = [i for i, l in enumerate(lines) if OFFICER_HEADER_RE.match(l["text"])]

    parsed = []
    for ri, start in enumerate(case_starts):
        end = case_starts[ri + 1] if ri + 1 < len(case_starts) else len(lines)
        comp_idx = next((i for i in complainant_idxs if start < i < end), None)
        cplh_idx = next((i for i in complaint_hdr_idxs if start < i < end), None)
        offh_idx = next((i for i in officer_hdr_idxs if start < i < end), None)
        if comp_idx is None or cplh_idx is None or offh_idx is None:
            continue

        case_words = []
        for line in lines[start + 1:comp_idx]:
            case_words.extend(line["words"])
        comp_words = []
        for line in lines[comp_idx:cplh_idx]:
            comp_words.extend(line["words"])

        cpl_rows = []
        for line in lines[cplh_idx + 1:offh_idx]:
            cpl_rows.append(_parse_complaint_row(line["words"]))

        off_rows = []
        for line in lines[offh_idx + 1:end]:
            if OFFICER_ROW_RE.match(line["text"]):
                off_rows.append(_parse_officer_row(line["words"]))

        parsed.append({
            "case_kvs": _parse_case_info(case_words),
            "comp_kvs": _parse_complainant(comp_words),
            "cpl_rows": cpl_rows,
            "off_rows": off_rows,
        })
    return parsed


def _case_number(case_kvs):
    for kv in case_kvs:
        if kv["key"] == "Number":
            return kv["value"]
    return ""


def _build_record_nodes(parsed, has_metadata, metadata_strings):
    nodes = []
    next_id = 1
    if has_metadata:
        nodes.append({
            "id": f"n{next_id}",
            "type": "metadata",
            "content": metadata_strings,
            "relationship": {"parent_id": None, "note": ""},
        })
        next_id += 1

    case_id = f"n{next_id}"
    next_id += 1
    nodes.append({
        "id": case_id,
        "type": "key_value",
        "content": parsed["case_kvs"],
        "relationship": {"parent_id": None, "note": ""},
    })

    case_num = _case_number(parsed["case_kvs"])

    nodes.append({
        "id": f"n{next_id}",
        "type": "key_value",
        "content": parsed["comp_kvs"],
        "relationship": {
            "parent_id": case_id,
            "note": f"Complainant information for case {case_num}",
        },
    })
    next_id += 1

    nodes.append({
        "id": f"n{next_id}",
        "type": "table",
        "content": {
            "headers": list(COMPLAINT_HEADERS),
            "rows": parsed["cpl_rows"],
        },
        "relationship": {
            "parent_id": case_id,
            "note": f"Complaints filed in case {case_num}",
        },
    })
    next_id += 1

    nodes.append({
        "id": f"n{next_id}",
        "type": "table",
        "content": {
            "headers": list(OFFICER_HEADERS),
            "rows": parsed["off_rows"],
        },
        "relationship": {
            "parent_id": case_id,
            "note": f"Officers involved in case {case_num}",
        },
    })

    return nodes


# --- Public API -----------------------------------------------------------

def extract(pdf_path: str) -> dict:
    base = os.path.splitext(os.path.basename(pdf_path))[0]
    if base.endswith("__sample"):
        base = base[: -len("__sample")]

    all_parsed = []
    metadata_strings = []
    sampled_pages = 0

    with pdfplumber.open(pdf_path) as pdf:
        sampled_pages = len(pdf.pages)
        for page_idx, page in enumerate(pdf.pages):
            words = page.extract_words(keep_blank_chars=False, use_text_flow=False)
            lines = _group_lines(words, y_tol=3.0)
            if page_idx == 0:
                metadata_strings = _build_metadata(lines)
            all_parsed.extend(_parse_records_on_page(lines))

    records = []
    for ri, parsed in enumerate(all_parsed):
        has_meta = (ri == 0)
        nodes = _build_record_nodes(parsed, has_meta, metadata_strings)
        records.append({"record_id": f"r{ri + 1}", "nodes": nodes})

    return {
        "doc_name": base,
        "model": "code-extractor",
        "sampled_pages": sampled_pages,
        "records": records,
    }


if __name__ == "__main__":
    import json
    import sys

    path = sys.argv[1] if len(sys.argv) > 1 else "/home/yiminglin/twix2.0/.tmp_pipeline/samples/Investigations_Redacted__sample.pdf"
    print(json.dumps(extract(path), indent=2))
