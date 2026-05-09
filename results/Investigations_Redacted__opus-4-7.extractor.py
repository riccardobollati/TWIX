"""Layout-aware extractor for Champaign PD 'Complaints By Date' (Investigations) report."""
import os
import re
import pdfplumber


def _cluster_lines(words, y_tol=3):
    if not words:
        return []
    sw = sorted(words, key=lambda w: w["top"])
    clusters = []
    cur = {"y_min": sw[0]["top"], "y_max": sw[0]["top"], "words": [sw[0]]}
    for w in sw[1:]:
        if w["top"] - cur["y_max"] <= y_tol:
            cur["words"].append(w)
            if w["top"] > cur["y_max"]:
                cur["y_max"] = w["top"]
        else:
            clusters.append(cur)
            cur = {"y_min": w["top"], "y_max": w["top"], "words": [w]}
    clusters.append(cur)
    for c in clusters:
        c["words"].sort(key=lambda w: w["x0"])
        c["text"] = " ".join(w["text"] for w in c["words"])
    return clusters


def _col_text(words, x0, x1):
    cw = [w for w in words if x0 <= w["x0"] < x1]
    cw.sort(key=lambda w: w["x0"])
    return " ".join(w["text"] for w in cw).strip()


def extract(pdf_path: str) -> dict:
    doc_name = os.path.splitext(os.path.basename(pdf_path))[0]
    if doc_name.endswith("__sample"):
        doc_name = doc_name[: -len("__sample")]

    records = []

    with pdfplumber.open(pdf_path) as pdf:
        sampled_pages = len(pdf.pages)

        for page_idx, page in enumerate(pdf.pages):
            page_num = page_idx + 1
            words = page.extract_words(use_text_flow=True, keep_blank_chars=False)
            clusters = _cluster_lines(words, y_tol=3)
            if not clusters:
                continue

            # Footer cluster (page label)
            footer_i = len(clusters)
            page_str = str(page_num)
            total_pages = "74"
            for j in range(len(clusters) - 1, -1, -1):
                t = clusters[j]["text"]
                m = re.search(r"Page\s+(\d+)\s+of\s+(\d+)", t)
                if m and ("L.E.A." in t or j == len(clusters) - 1):
                    footer_i = j
                    page_str = m.group(1)
                    total_pages = m.group(2)
                    break
            page_label = f"Page {page_str} of {total_pages}"

            # Report Criteria (only on page 1)
            report_criteria = None
            for c in clusters[:4]:
                if c["text"].startswith("Report Criteria"):
                    report_criteria = c["text"]
                    break

            standard_metadata = [
                "Champaign Police Department",
                "Complaints By Date",
                "Complaints Detail Rpt #A-2",
                "L.E.A. Data Technologies ADMINISTRATIVE Database",
                page_label,
            ]

            # Find each case-header cluster
            case_header_indices = [
                i for i, c in enumerate(clusters)
                if c["text"].startswith("Date Number Investigator")
            ]

            for rec_idx_on_page, header_i in enumerate(case_header_indices):
                if rec_idx_on_page + 1 < len(case_header_indices):
                    end_i = case_header_indices[rec_idx_on_page + 1]
                else:
                    end_i = footer_i

                # Locate sub-section markers
                comp_i = None
                cmpl_hdr_i = None
                off_hdr_i = None
                for j in range(header_i + 1, end_i):
                    t = clusters[j]["text"]
                    if comp_i is None and t.startswith("Complainant:"):
                        comp_i = j
                    elif cmpl_hdr_i is None and t.startswith("Type Of Complaint"):
                        cmpl_hdr_i = j
                    elif off_hdr_i is None and t.startswith("Name ID No."):
                        off_hdr_i = j

                # Build metadata content
                if page_num == 1 and rec_idx_on_page == 0 and report_criteria:
                    md_content = [report_criteria] + standard_metadata
                else:
                    md_content = list(standard_metadata)

                nodes = []
                nodes.append({
                    "id": "n1",
                    "type": "metadata",
                    "content": md_content,
                    "relationship": {"parent_id": None, "note": ""},
                })

                # ---- n2: case header (top kv table) ----
                end_case_i = comp_i if comp_i is not None else (
                    cmpl_hdr_i if cmpl_hdr_i is not None else end_i
                )
                case_words = []
                for j in range(header_i + 1, end_case_i):
                    case_words.extend(clusters[j]["words"])

                if case_words:
                    ys = [w["top"] for w in case_words]
                    midpoint = (min(ys) + max(ys)) / 2.0
                    row1 = [w for w in case_words if w["top"] <= midpoint]
                    row2 = [w for w in case_words if w["top"] > midpoint]
                else:
                    row1, row2 = [], []

                kv = [
                    {"key": "Date", "value": _col_text(row1, 40, 100)},
                    {"key": "Number", "value": _col_text(row1, 100, 161) or _col_text(row2, 100, 161)},
                    {"key": "Investigator", "value": _col_text(row1, 161, 220) or _col_text(row2, 161, 220)},
                    {"key": "Date Assigned", "value": _col_text(row2, 220, 280) or _col_text(row1, 220, 280)},
                    {"key": "Racial", "value": _col_text(row1 + row2, 280, 310)},
                    {"key": "Category", "value": _col_text(row1, 310, 402)},
                    {"key": "Type", "value": _col_text(row2, 310, 402)},
                    {"key": "Location Of Occurrence", "value": _col_text(row1 + row2, 402, 583)},
                    {"key": "Disposition", "value": _col_text(row1, 583, 636) or _col_text(row2, 583, 636)},
                    {"key": "Completed", "value": _col_text(row2, 636, 680) or _col_text(row1, 636, 680)},
                    {"key": "Recorded On Camera", "value": _col_text(row1, 680, 800)},
                    {"key": "Body Cam Availability", "value": _col_text(row2, 680, 800)},
                ]
                nodes.append({
                    "id": "n2",
                    "type": "key_value",
                    "content": kv,
                    "relationship": {"parent_id": "n1", "note": "case header information for this complaint record"},
                })

                # ---- n3: complainant kv ----
                if comp_i is not None:
                    cw = clusters[comp_i]["words"]
                    label_set = {"Complainant:", "DOB:", "Gender:", "Address:", "H", "Phone:"}

                    def vt(x0, x1):
                        vw = [w for w in cw if x0 <= w["x0"] < x1 and w["text"] not in label_set]
                        vw.sort(key=lambda w: w["x0"])
                        return " ".join(w["text"] for w in vw).strip()

                    comp_kv = [
                        {"key": "Complainant", "value": vt(100, 240)},
                        {"key": "DOB", "value": vt(275, 317)},
                        {"key": "Gender", "value": vt(340, 387)},
                        {"key": "Address", "value": vt(410, 660)},
                        {"key": "H Phone", "value": vt(690, 800)},
                    ]
                    nodes.append({
                        "id": "n3",
                        "type": "key_value",
                        "content": comp_kv,
                        "relationship": {"parent_id": "n2", "note": "complainant details for this case"},
                    })

                # ---- n4: complaint table ----
                if cmpl_hdr_i is not None:
                    cstart = cmpl_hdr_i + 1
                    cend = off_hdr_i if off_hdr_i is not None else end_i
                    crows = []
                    for j in range(cstart, cend):
                        cwd = clusters[j]["words"]
                        if not cwd:
                            continue
                        text = clusters[j]["text"]
                        m = re.match(r"^Complaint\s+#:?(\d+)", text)
                        if m:
                            num = m.group(1)
                            type_text = " ".join(w["text"] for w in cwd if 230 <= w["x0"] < 466).strip()
                            desc_text = " ".join(w["text"] for w in cwd if 466 <= w["x0"] < 643).strip()
                            disp_text = " ".join(w["text"] for w in cwd if 643 <= w["x0"]).strip()
                            crows.append([
                                {"key": "Complaint #", "value": num},
                                {"key": "Type Of Complaint", "value": type_text},
                                {"key": "Description", "value": desc_text},
                                {"key": "Complaint Disposition", "value": disp_text},
                            ])
                    nodes.append({
                        "id": "n4",
                        "type": "table",
                        "content": {
                            "headers": ["Complaint #", "Type Of Complaint", "Description", "Complaint Disposition"],
                            "rows": crows,
                        },
                        "relationship": {"parent_id": "n2", "note": "list of complaint allegations for this case"},
                    })

                # ---- n5: officer table ----
                if off_hdr_i is not None:
                    ostart = off_hdr_i + 1
                    oend = end_i
                    orows = []
                    last_row = None
                    for j in range(ostart, oend):
                        cwd = clusters[j]["words"]
                        if not cwd:
                            continue
                        text = clusters[j]["text"]
                        m = re.match(r"^Officer\s+#:?(\d+)", text)
                        if m:
                            num = m.group(1)
                            name_t = " ".join(w["text"] for w in cwd if 230 <= w["x0"] < 371).strip()
                            id_t = " ".join(w["text"] for w in cwd if 371 <= w["x0"] < 416).strip()
                            rank_t = " ".join(w["text"] for w in cwd if 416 <= w["x0"] < 484).strip()
                            div_t = " ".join(w["text"] for w in cwd if 484 <= w["x0"] < 553).strip()
                            disp_t = " ".join(w["text"] for w in cwd if 553 <= w["x0"] < 643).strip()
                            act_t = " ".join(w["text"] for w in cwd if 643 <= w["x0"] < 714).strip()
                            body_t = " ".join(w["text"] for w in cwd if 714 <= w["x0"]).strip()
                            row = [
                                {"key": "Officer #", "value": num},
                                {"key": "Name", "value": name_t},
                                {"key": "ID No.", "value": id_t},
                                {"key": "Rank", "value": rank_t},
                                {"key": "Division", "value": div_t},
                                {"key": "Officer Disposition", "value": disp_t},
                                {"key": "Action Taken", "value": act_t},
                                {"key": "Body Cam", "value": body_t},
                            ]
                            orows.append(row)
                            last_row = row
                        else:
                            if last_row is None:
                                continue
                            for w in cwd:
                                x = w["x0"]
                                t = w["text"]
                                if 230 <= x < 371:
                                    last_row[1]["value"] = (last_row[1]["value"] + t).strip()
                                elif 371 <= x < 416:
                                    last_row[2]["value"] = (last_row[2]["value"] + t).strip()
                                elif 416 <= x < 484:
                                    last_row[3]["value"] = (last_row[3]["value"] + t).strip()
                                elif 484 <= x < 553:
                                    last_row[4]["value"] = (last_row[4]["value"] + t).strip()
                                elif 553 <= x < 643:
                                    last_row[5]["value"] = (last_row[5]["value"] + t).strip()
                                elif 643 <= x < 714:
                                    last_row[6]["value"] = (last_row[6]["value"] + t).strip()
                                elif x >= 714:
                                    last_row[7]["value"] = (last_row[7]["value"] + t).strip()
                    nodes.append({
                        "id": "n5",
                        "type": "table",
                        "content": {
                            "headers": ["Officer #", "Name", "ID No.", "Rank", "Division", "Officer Disposition", "Action Taken", "Body Cam"],
                            "rows": orows,
                        },
                        "relationship": {"parent_id": "n2", "note": "officers involved in this case"},
                    })

                records.append({
                    "record_id": f"r{len(records) + 1}",
                    "nodes": nodes,
                })

    return {
        "doc_name": doc_name,
        "model": "code-extractor",
        "sampled_pages": sampled_pages,
        "records": records,
    }
