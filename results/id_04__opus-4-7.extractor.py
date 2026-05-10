"""Extractor for U.S. International Trade in Goods and Services PDF.

Each page contains a banner (3 lines) and yearly tables with 13 rows
(annual total + 12 months) of trade data. We produce one record per year.
"""

import os
import re

import pdfplumber

HEADERS = [
    "Period",
    "Balance Total",
    "Balance Goods",
    "Balance Services",
    "Exports Total",
    "Exports Goods",
    "Exports Services",
    "Imports Total",
    "Imports Goods",
    "Imports Services",
]

BANNER_LINES = [
    "U.S. International Trade in Goods and Services, 1992 - Present",
    "In millions of dollars. Seasonally adjusted; details may not equal totals due to seasonal adjustment and rounding.",
    "Goods data presented on a Balance of Payments (BOP) Basis. Source: U.S. Census Bureau, Foreign Trade Division.",
]

NUM = r"-?[\d,]+"
ROW_RE = re.compile(
    r"^(Jan\.\s*-\s*Dec\.|January|February|March|April|May|June|July|August|September|October|November|December)\s+"
    + r"\s+".join([f"({NUM})"] * 9)
    + r"\s*$"
)
YEAR_RE = re.compile(r"^(\d{4})\s*$")


def _normalize_period(p: str) -> str:
    p = p.strip()
    if p.lower().startswith("jan") and "dec" in p.lower():
        return "Jan. - Dec."
    return p


def extract(pdf_path: str) -> dict:
    doc_name = os.path.splitext(os.path.basename(pdf_path))[0]

    # Group lines into (year -> list of row tuples), preserving order of years
    year_rows: dict[str, list[tuple]] = {}
    year_order: list[str] = []
    current_year: str | None = None

    with pdfplumber.open(pdf_path) as pdf:
        sampled_pages = len(pdf.pages)
        for page in pdf.pages:
            text = page.extract_text() or ""
            for raw_line in text.split("\n"):
                line = raw_line.strip()
                if not line:
                    continue
                ym = YEAR_RE.match(line)
                if ym:
                    current_year = ym.group(1)
                    if current_year not in year_rows:
                        year_rows[current_year] = []
                        year_order.append(current_year)
                    continue
                rm = ROW_RE.match(line)
                if rm and current_year is not None:
                    period = _normalize_period(rm.group(1))
                    values = [rm.group(i) for i in range(2, 11)]
                    year_rows[current_year].append((period, values))

    records = []
    for idx, year in enumerate(year_order, start=1):
        rows_data = year_rows[year]
        # Build table rows
        table_rows = []
        for period, vals in rows_data:
            row = [{"key": HEADERS[0], "value": period}]
            for h, v in zip(HEADERS[1:], vals):
                row.append({"key": h, "value": v})
            table_rows.append(row)

        metadata_content = list(BANNER_LINES) + [f"Year: {year}"]

        nodes = [
            {
                "id": "n1",
                "type": "metadata",
                "content": metadata_content,
                "relationship": {"parent_id": None, "note": ""},
            },
            {
                "id": "n2",
                "type": "table",
                "content": {"headers": list(HEADERS), "rows": table_rows},
                "relationship": {
                    "parent_id": "n1",
                    "note": f"Monthly trade data for {year} under year heading",
                },
            },
        ]
        records.append({"record_id": f"r{idx}", "nodes": nodes})

    return {
        "doc_name": doc_name,
        "model": "code-extractor",
        "sampled_pages": sampled_pages,
        "records": records,
    }


if __name__ == "__main__":
    import sys
    print("wrote extractor.py")
