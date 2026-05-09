"""Stage 1 step 1 — sample first N pages of a PDF.

agent_data_extraction.md §2: take the first 5 pages (or all if fewer).
"""

from __future__ import annotations

from pathlib import Path

from pypdf import PdfReader, PdfWriter


def sample_first_pages(pdf_path: str | Path, out_path: str | Path, n_pages: int = 5) -> int:
    """Write the first n_pages of `pdf_path` to `out_path`. Return number of pages written."""
    pdf_path = Path(pdf_path)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    reader = PdfReader(str(pdf_path))
    total = len(reader.pages)
    take = min(n_pages, total)
    writer = PdfWriter()
    for i in range(take):
        writer.add_page(reader.pages[i])
    with open(out_path, "wb") as f:
        writer.write(f)
    return take
