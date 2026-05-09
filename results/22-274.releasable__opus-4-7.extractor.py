"""Extractor for University of Illinois Police Department Use Of Force reports.

Each PDF page corresponds to one record. A record contains:
  - n1: metadata banner (titles + page footer)
  - n2: incident-level key/value block (Case Number ... Notes)
  - n3..nM: one key/value block per Subject
  - nM+1: officers table (one row per Officer line pair)
  - nM+2: narrative key/value
"""

import os
import re

import pdfplumber


INCIDENT_KEYS = [
    "Case Number", "Date", "Time", "Assist", "Agency", "Information Taken From",
    "Status", "Incident Reviewed By", "Date Reviewed", "Drugs/Alcohol",
    "Location", "City", "K-9", "Crisis Intervention Related",
    "Type Premises", "District", "Recorded On Camera", "Camera",
    "Type Situation", "Reason Force Used", "Officer Injured",
    "Danger Factors", "Final Disposition", "Verbal De-Escalation Attempted",
    "Notes",
]

SUBJECT_KEY_ORDER = [
    "Subject #", "Name", "DOB", "Gender", "Race", "HGT", "WGT",
    "Under The Influence", "Address", "City", "Level Of Resistance",
    "Subject Armed With", "Force Used", "Force Location", "Arrested",
    "Arrested For", "Arrest ID", "Injured", "Type Injuries", "Medical Aid",
    "Notes",
]

SUBJECT_MIDDLE_KEYS = [
    "DOB", "Gender", "Race", "HGT", "WGT", "Under The Influence",
    "Address", "City", "Level Of Resistance", "Subject Armed With",
    "Force Used", "Force Location", "Arrested", "Arrested For", "Arrest ID",
    "Injured", "Type Injuries", "Medical Aid",
]

OFFICER_HEADERS = [
    "Officer", "Action Taken", "Action Taken Useful", "Camera", "CIT",
    "Type Injuries", "Disciplinary Action", "Included On Alert",
]


def _make_key_pattern(key: str):
    parts = key.split()
    pat = r"\s+".join(re.escape(p) for p in parts)
    return re.compile(r"(?<![A-Za-z0-9])" + pat + r"\s*:")


def _parse_kv_block(text: str, keys):
    """Locate each key (longest first, no overlapping) and capture the
    value up to the next key.  Returns dict with all keys present."""
    keys_sorted = sorted(keys, key=lambda k: -len(k))
    found = []        # [(key, start, end)]
    matched = []      # [(start, end)] consumed regions
    for key in keys_sorted:
        pattern = _make_key_pattern(key)
        for m in pattern.finditer(text):
            if any(m.start() < me and m.end() > ms for ms, me in matched):
                continue
            found.append((key, m.start(), m.end()))
            matched.append((m.start(), m.end()))
            break
    found.sort(key=lambda x: x[1])
    result = {k: "" for k in keys}
    for i, (key, _s, e) in enumerate(found):
        if i + 1 < len(found):
            value = text[e:found[i + 1][1]]
        else:
            value = text[e:]
        result[key] = value.strip()
    return result


def _parse_subject(text: str) -> dict:
    result = {k: "" for k in SUBJECT_KEY_ORDER}

    # Subject # and Name (the name is unkeyed: it sits between the number and DOB:)
    m = re.match(
        r"\s*Subject\s*#\s*:\s*(\d+)\s*(.*?)\s*(?=\bDOB\s*:)",
        text, re.DOTALL,
    )
    if m:
        result["Subject #"] = m.group(1).strip()
        result["Name"] = m.group(2).strip()
        rest_start = m.end()
    else:
        m2 = re.match(r"\s*Subject\s*#\s*:\s*(\d+)", text)
        if m2:
            result["Subject #"] = m2.group(1).strip()
            rest_start = m2.end()
        else:
            rest_start = 0

    # Notes is either "Notes: <text>" at the end or the literal "No Notes".
    notes_value = ""
    cut_pos = len(text)
    notes_match = re.search(r"\bNotes\s*:\s*(.*)$", text, re.DOTALL)
    if notes_match:
        notes_value = re.sub(r"\s+", " ", notes_match.group(1)).strip()
        cut_pos = notes_match.start()
    else:
        nn_match = re.search(r"\bNo\s+Notes\s*$", text)
        if nn_match:
            notes_value = "No Notes"
            cut_pos = nn_match.start()

    middle_text = text[rest_start:cut_pos]
    middle_kv = _parse_kv_block(middle_text, SUBJECT_MIDDLE_KEYS)

    # The PDF prints "HGT: / WGT:" with a literal slash separator; strip it.
    hgt = middle_kv.get("HGT", "")
    if hgt.endswith("/"):
        middle_kv["HGT"] = hgt.rstrip("/").strip()

    result.update(middle_kv)
    result["Notes"] = notes_value
    return result


def extract(pdf_path: str) -> dict:
    doc_name = os.path.splitext(os.path.basename(pdf_path))[0]
    records = []

    with pdfplumber.open(pdf_path) as pdf:
        sampled_pages = len(pdf.pages)
        for page_idx, page in enumerate(pdf.pages):
            full_text = page.extract_text() or ""
            raw_lines = full_text.split("\n")
            lines = [ln for ln in raw_lines if ln.strip()]

            # ---------- metadata ----------
            meta = []
            for ln in lines:
                if ln.startswith("Report Criteria"):
                    meta.append(ln.strip())
                    break
            meta.append("University of Illinois Police Department")
            meta.append("Use Of Force Full Details")

            page_match = re.search(r"Page\s+(\d+)\s+of\s+(\d+)", full_text)
            if page_match:
                page_num, total = page_match.group(1), page_match.group(2)
            else:
                page_num, total = str(page_idx + 1), str(sampled_pages)
            meta.append(f"Officer Detail Reports #A-12 Page {page_num} of {total}")

            for ln in lines:
                if ln.startswith("L.E.A."):
                    meta.append(ln.strip())
                    break

            nodes = []
            n_idx = 1
            nodes.append({
                "id": f"n{n_idx}",
                "type": "metadata",
                "content": meta,
                "relationship": {"parent_id": None, "note": ""},
            })
            n_idx += 1

            # ---------- block boundaries ----------
            case_idx = None
            subject_indices = []
            narrative_idx = None
            footer_idx = None
            for i, ln in enumerate(lines):
                if case_idx is None and ln.startswith("Case Number"):
                    case_idx = i
                elif ln.startswith("Subject #"):
                    subject_indices.append(i)
                elif narrative_idx is None and ln.startswith("Narrative:"):
                    narrative_idx = i
                elif footer_idx is None and ln.startswith("L.E.A."):
                    footer_idx = i

            officer_indices = []
            for i, ln in enumerate(lines):
                if narrative_idx is not None and i >= narrative_idx:
                    break
                if ln.startswith("Officer:"):
                    officer_indices.append(i)

            # ---------- incident node ----------
            if case_idx is not None:
                if subject_indices:
                    inc_end = subject_indices[0]
                elif officer_indices:
                    inc_end = officer_indices[0]
                elif narrative_idx is not None:
                    inc_end = narrative_idx
                else:
                    inc_end = footer_idx if footer_idx is not None else len(lines)
                incident_text = " ".join(lines[case_idx:inc_end])
                inc_kv = _parse_kv_block(incident_text, INCIDENT_KEYS)
                incident_id = f"n{n_idx}"
                nodes.append({
                    "id": incident_id,
                    "type": "key_value",
                    "content": [{"key": k, "value": inc_kv[k]} for k in INCIDENT_KEYS],
                    "relationship": {"parent_id": None, "note": ""},
                })
                n_idx += 1
            else:
                incident_id = None

            # ---------- subject nodes ----------
            for si, sidx in enumerate(subject_indices):
                if si + 1 < len(subject_indices):
                    next_idx = subject_indices[si + 1]
                elif officer_indices:
                    next_idx = officer_indices[0]
                elif narrative_idx is not None:
                    next_idx = narrative_idx
                else:
                    next_idx = footer_idx if footer_idx is not None else len(lines)
                subj_text = " ".join(lines[sidx:next_idx])
                subj_kv = _parse_subject(subj_text)
                nodes.append({
                    "id": f"n{n_idx}",
                    "type": "key_value",
                    "content": [{"key": k, "value": subj_kv.get(k, "")} for k in SUBJECT_KEY_ORDER],
                    "relationship": {
                        "parent_id": incident_id,
                        "note": "Subject involved in incident",
                    },
                })
                n_idx += 1

            # ---------- officers table ----------
            if officer_indices:
                rows = []
                for oi, oidx in enumerate(officer_indices):
                    if oi + 1 < len(officer_indices):
                        end_idx = officer_indices[oi + 1]
                    elif narrative_idx is not None:
                        end_idx = narrative_idx
                    else:
                        end_idx = footer_idx if footer_idx is not None else len(lines)
                    block = " ".join(lines[oidx:end_idx])
                    off_kv = _parse_kv_block(block, OFFICER_HEADERS)
                    row = [{"key": h, "value": off_kv[h]} for h in OFFICER_HEADERS]
                    rows.append(row)
                nodes.append({
                    "id": f"n{n_idx}",
                    "type": "table",
                    "content": {
                        "headers": list(OFFICER_HEADERS),
                        "rows": rows,
                    },
                    "relationship": {
                        "parent_id": incident_id,
                        "note": "Officers involved in incident",
                    },
                })
                n_idx += 1

            # ---------- narrative ----------
            if narrative_idx is not None:
                end_n = footer_idx if footer_idx is not None else len(lines)
                narr_text = " ".join(lines[narrative_idx:end_n])
                m = re.match(r"Narrative\s*:\s*(.*)", narr_text, re.DOTALL)
                value = m.group(1) if m else narr_text
                value = re.sub(r"\s+", " ", value).strip()
                nodes.append({
                    "id": f"n{n_idx}",
                    "type": "key_value",
                    "content": [{"key": "Narrative", "value": value}],
                    "relationship": {
                        "parent_id": incident_id,
                        "note": "Narrative description of incident",
                    },
                })
                n_idx += 1

            records.append({
                "record_id": f"r{page_idx + 1}",
                "nodes": nodes,
            })

    return {
        "doc_name": doc_name,
        "model": "code-extractor",
        "sampled_pages": sampled_pages,
        "records": records,
    }
