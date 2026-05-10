import os
import re
import pdfplumber


METADATA = [
    "University of Utah",
    "General Stores",
    "Cylinder Billing Report",
    "Date: 07/31/2020",
]

HEADERS = [
    "BarCode",
    "Gas",
    "Size",
    "CO #",
    "Location",
    "Demurrage",
    "Delivery Code",
]


def _bucket(x0):
    if x0 < 40:
        return "BarCode"
    if x0 < 80:
        return None
    if x0 < 180:
        return "Gas"
    if x0 < 275:
        return "Size"
    if x0 < 380:
        return "CO #"
    if x0 < 600:
        return "Location"
    if x0 < 660:
        return "Demurrage"
    return "Delivery Code"


def _cluster_rows(words, y_tol=3.0):
    words = sorted(words, key=lambda w: (w["top"], w["x0"]))
    rows = []
    cur = []
    prev = None
    for w in words:
        if prev is None or w["top"] - prev <= y_tol:
            cur.append(w)
        else:
            rows.append(sorted(cur, key=lambda x: x["x0"]))
            cur = [w]
        prev = w["top"]
    if cur:
        rows.append(sorted(cur, key=lambda x: x["x0"]))
    return rows


def _build_record(record_id, chart, table_rows, total):
    nodes = [
        {
            "id": "n1",
            "type": "metadata",
            "content": list(METADATA),
            "relationship": {"parent_id": None, "note": ""},
        },
        {
            "id": "n2",
            "type": "key_value",
            "content": [{"key": "Chart", "value": chart}],
            "relationship": {
                "parent_id": "n1",
                "note": "chart group under report header",
            },
        },
        {
            "id": "n3",
            "type": "table",
            "content": {
                "headers": list(HEADERS),
                "rows": [
                    [{"key": h, "value": row.get(h, "")} for h in HEADERS]
                    for row in table_rows
                ],
            },
            "relationship": {
                "parent_id": "n2",
                "note": "cylinder rows for this chart",
            },
        },
        {
            "id": "n4",
            "type": "key_value",
            "content": [{"key": "Amount Total", "value": total or ""}],
            "relationship": {
                "parent_id": "n2",
                "note": "subtotal for this chart",
            },
        },
    ]
    return {"record_id": record_id, "nodes": nodes}


def extract(pdf_path: str) -> dict:
    doc_name = os.path.splitext(os.path.basename(pdf_path))[0]

    records = []
    cur_chart = None
    cur_rows = []
    cur_total = None

    def flush():
        nonlocal cur_chart, cur_rows, cur_total
        if cur_chart is None:
            return
        rid = f"r{len(records) + 1}"
        records.append(_build_record(rid, cur_chart, cur_rows, cur_total))
        cur_chart = None
        cur_rows = []
        cur_total = None

    with pdfplumber.open(pdf_path) as pdf:
        page_count = len(pdf.pages)
        for page in pdf.pages:
            words = page.extract_words(use_text_flow=True, keep_blank_chars=False)
            rows = _cluster_rows(words)

            for row in rows:
                texts = [w["text"] for w in row]

                # Banner / header / footer rows: skip.
                if any(t in ("University", "Date:", "Page:", "BarCode") for t in texts):
                    continue
                if any(t.startswith("CylBillAcct") for t in texts):
                    continue
                # "General Stores" + "Cylinder Billing Report" are skipped via banner above.
                if "General" in texts and "Stores" in texts:
                    continue
                if "Cylinder" in texts and "Billing" in texts:
                    continue

                # Chart row.
                if "Chart" in texts:
                    flush()
                    chart_num = ""
                    for w in row:
                        t = w["text"]
                        if t.isdigit() and len(t) >= 10:
                            chart_num = t
                            break
                    cur_chart = chart_num
                    continue

                # Amount Total row.
                if "Amount" in texts and "Total" in texts:
                    val = ""
                    for w in row:
                        if w["x0"] >= 600 and re.match(r"^-?\d+(\.\d+)?$", w["text"]):
                            val = w["text"]
                            break
                    cur_total = val
                    continue

                # Data row: first word in BarCode bucket and numeric.
                if not row:
                    continue
                first = row[0]
                if not (first["x0"] < 40 and first["text"].isdigit()):
                    continue
                if cur_chart is None:
                    continue

                cols = {h: [] for h in HEADERS}
                for w in row:
                    bucket = _bucket(w["x0"])
                    if bucket is None:
                        continue
                    cols[bucket].append(w["text"])
                row_data = {h: " ".join(cols[h]).strip() for h in HEADERS}
                cur_rows.append(row_data)

        flush()

    return {
        "doc_name": doc_name,
        "model": "code-extractor",
        "sampled_pages": page_count,
        "records": records,
    }
