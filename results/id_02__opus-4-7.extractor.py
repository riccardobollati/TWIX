import os
import pdfplumber

HEADERS = [
    "Project Name",
    "File Number",
    "Location",
    "Project Description",
    "Project Manager",
    "Project Status",
    "Applicant",
]


def _find_row_dividers(page):
    rects = page.rects
    dividers = [
        r for r in rects
        if (r["bottom"] - r["top"]) < 2 and (r["x1"] - r["x0"]) > 100
    ]
    return sorted(set(round(r["top"], 2) for r in dividers))


def _find_column_bounds(page):
    rects = page.rects
    headers = [
        r for r in rects
        if r.get("tag") == "TH"
        and (r["x1"] - r["x0"]) > 50
        and (r["bottom"] - r["top"]) > 25
    ]
    headers.sort(key=lambda r: r["x0"])
    if len(headers) != 7:
        return None
    return [(h["x0"], h["x1"]) for h in headers]


def _assign_to_column(word, col_bounds):
    cx = (word["x0"] + word["x1"]) / 2.0
    n = len(col_bounds)
    for i, (x0, x1) in enumerate(col_bounds):
        if i == n - 1:
            if x0 <= cx <= x1 + 1.5:
                return i
        else:
            if x0 - 0.5 <= cx < x1:
                return i
    return None


def _cell_text(words):
    if not words:
        return ""
    words = sorted(words, key=lambda w: (round(w["top"], 1), w["x0"]))
    lines = []
    cur_line = []
    cur_top = None
    for w in words:
        if cur_top is None or abs(w["top"] - cur_top) <= 3.5:
            cur_line.append(w)
            if cur_top is None:
                cur_top = w["top"]
        else:
            lines.append(cur_line)
            cur_line = [w]
            cur_top = w["top"]
    if cur_line:
        lines.append(cur_line)

    line_texts = []
    for line in lines:
        line.sort(key=lambda w: w["x0"])
        line_texts.append(" ".join(w["text"] for w in line))

    result = ""
    for lt in line_texts:
        if not result:
            result = lt
        elif result.endswith("-"):
            result = result + lt
        else:
            result = result + " " + lt
    return result.strip()


def _extract_page(page, page_num):
    div_tops = _find_row_dividers(page)
    col_bounds = _find_column_bounds(page)

    metadata_node = {
        "id": "n1",
        "type": "metadata",
        "content": [
            "Active Developments Log | September 2018",
            f"Page {page_num}",
        ],
        "relationship": {"parent_id": None, "note": ""},
    }

    rows_data = []
    if col_bounds is not None and len(div_tops) >= 3:
        words = page.extract_words(x_tolerance=2, y_tolerance=3)
        for ri in range(1, len(div_tops) - 1):
            top = div_tops[ri]
            bot = div_tops[ri + 1]
            row_words = [
                w for w in words
                if w["top"] >= top - 0.5 and w["bottom"] <= bot + 0.5
            ]
            cells = [[] for _ in HEADERS]
            for w in row_words:
                ci = _assign_to_column(w, col_bounds)
                if ci is not None:
                    cells[ci].append(w)
            row = [
                {"key": HEADERS[ci], "value": _cell_text(cells[ci])}
                for ci in range(len(HEADERS))
            ]
            rows_data.append(row)

    table_node = {
        "id": "n2",
        "type": "table",
        "content": {"headers": list(HEADERS), "rows": rows_data},
        "relationship": {
            "parent_id": "n1",
            "note": f"Active developments table on page {page_num}",
        },
    }

    return [metadata_node, table_node]


def extract(pdf_path: str) -> dict:
    doc_name = os.path.splitext(os.path.basename(pdf_path))[0]
    records = []
    with pdfplumber.open(pdf_path) as pdf:
        sampled = len(pdf.pages)
        for pi, page in enumerate(pdf.pages):
            page_num = pi + 1
            nodes = _extract_page(page, page_num)
            records.append({"record_id": f"r{page_num}", "nodes": nodes})

    return {
        "doc_name": doc_name,
        "model": "code-extractor",
        "sampled_pages": sampled,
        "records": records,
    }
