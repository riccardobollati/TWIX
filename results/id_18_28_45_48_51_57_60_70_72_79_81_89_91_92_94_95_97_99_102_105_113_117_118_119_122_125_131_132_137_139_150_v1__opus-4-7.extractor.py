"""Extractor for WideOrbit broadcast invoice PDFs.

Each page of the PDF is treated as a separate record. The layout is
column-oriented (station block, property/invoice key/value blocks, billing
address, send-payment-to, lines table, and per-line spot tables).
"""

import os
import re
import pdfplumber


LINE_HEADERS = [
    "Line", "Start Date", "End Date", "Description", "Start/End Time",
    "MTWTFSS", "Length", "Spots/Week", "Rate", "Type",
]

SPOT_HEADERS = [
    "#", "Ch", "Day", "Air Date", "Air Time", "Description",
    "Start/End Time", "Length", "Ad-ID", "Rate", "Type",
]

# x boundaries [low, high) for the lines summary table columns
LINE_COL_X = [
    (28, 41),
    (41, 88),
    (88, 137),
    (137, 229),
    (229, 305),
    (305, 376),
    (376, 413),
    (413, 455),
    (455, 505),
    (505, 605),
]

# x boundaries for the spots subtable columns
SPOT_COL_X = [
    (45, 65),
    (65, 95),
    (95, 115),
    (115, 156),
    (156, 195),
    (195, 315),
    (315, 385),
    (385, 410),
    (410, 530),
    (530, 575),
    (575, 605),
]

# Known n4 keys (account/billing/sales metadata)
N4_KEYS = [
    "Account Executive", "Sales Office", "Sales Region",
    "Agency Code", "Advertiser Code",
    "Billing Calendar", "Billing Type", "Special Handling",
    "Agency Ref", "Advertiser Ref",
    "Product 1", "Product 2",
]
N4_KEY_SET = set(N4_KEYS)

# Known n3 keys (property/invoice/order metadata)
N3_A_KEYS = [
    "Property", "Invoice #", "Invoice Date", "Invoice Month",
    "Invoice Period", "Advertiser", "Product", "Estimate #",
]
N3_B_KEYS = ["Order #", "Alt Order #", "Deal #", "Flight Dates"]


def _cluster_lines(words, tol=2.5):
    """Cluster words into visual rows by y-position."""
    if not words:
        return []
    sw = sorted(words, key=lambda w: (w['top'], w['x0']))
    rows = []
    cur = [sw[0]]
    cy = sw[0]['top']
    for w in sw[1:]:
        if abs(w['top'] - cy) <= tol:
            cur.append(w)
            cy = (cy + w['top']) / 2
        else:
            rows.append(sorted(cur, key=lambda x: x['x0']))
            cur = [w]
            cy = w['top']
    rows.append(sorted(cur, key=lambda x: x['x0']))
    return rows


def _row_text(row, sep=' '):
    return sep.join(w['text'] for w in row).strip()


def _row_min_y(row):
    return min(w['top'] for w in row) if row else 0


def _split_glued_time(word):
    """Split a glued word like 'AMSa-Su' or 'TUESDA7-9a' if applicable."""
    m = re.match(r'^(AM|PM)([A-Za-z].*)$', word)
    if m:
        return m.group(1), m.group(2)
    m = re.match(r'^([A-Za-z][A-Za-z\-/ ]*)(\d+[apAP]?-\d+[apAP]?)$', word)
    if m:
        return m.group(1), m.group(2)
    return word, None


def _words_to_columns(row, col_bounds):
    cols = [[] for _ in col_bounds]
    for w in row:
        for i, (lo, hi) in enumerate(col_bounds):
            if lo <= w['x0'] < hi:
                cols[i].append(w)
                break
    return cols


def _is_date(s):
    return bool(re.match(r'^\d{1,2}/\d{1,2}/\d{2,4}$', s))


def _detect_duplicate_marker(page):
    """Detect a widely-spaced D-U-P-L-I-C-A-T-E watermark near top of page."""
    chars = page.chars
    top_chars = sorted(
        [c for c in chars if c['top'] < 35 and c.get('text', '').isalpha()],
        key=lambda c: (c['top'], c['x0']),
    )
    target = list("DUPLICATE")
    txt = [c['text'] for c in top_chars]
    for i in range(len(txt)):
        j = i
        k = 0
        last_x = None
        while j < len(txt) and k < len(target):
            if txt[j] == target[k]:
                if last_x is not None and (top_chars[j]['x0'] - last_x) < 15:
                    j += 1
                    continue
                last_x = top_chars[j]['x0']
                k += 1
                j += 1
            else:
                j += 1
        if k == len(target):
            return True
    return False


def _parse_line_summary_row(row):
    """Parse a Lines-table row into a dict of {header: value}."""
    cols = _words_to_columns(row, LINE_COL_X)
    desc_col = list(cols[3])
    se_col = list(cols[4])
    new_desc_words = []
    for w in desc_col:
        left, right = _split_glued_time(w['text'])
        if right is not None:
            new_desc_words.append(left)
            se_col.append({'text': right, 'x0': w['x0']})
        else:
            new_desc_words.append(w['text'])
    desc_text = ' '.join(new_desc_words).strip()

    out = {
        LINE_HEADERS[0]: ' '.join(w['text'] for w in cols[0]).strip(),
        LINE_HEADERS[1]: ' '.join(w['text'] for w in cols[1]).strip(),
        LINE_HEADERS[2]: ' '.join(w['text'] for w in cols[2]).strip(),
        LINE_HEADERS[3]: desc_text,
        LINE_HEADERS[4]: ' '.join(w['text'] for w in sorted(se_col, key=lambda x: x['x0'])).strip(),
        LINE_HEADERS[5]: ' '.join(w['text'] for w in cols[5]).strip(),
        LINE_HEADERS[6]: ' '.join(w['text'] for w in cols[6]).strip(),
        LINE_HEADERS[7]: ' '.join(w['text'] for w in cols[7]).strip(),
        LINE_HEADERS[8]: ' '.join(w['text'] for w in cols[8]).strip(),
        LINE_HEADERS[9]: ' '.join(w['text'] for w in cols[9]).strip(),
    }
    return out


def _parse_spot_row(row):
    cols = _words_to_columns(row, SPOT_COL_X)
    at_col = cols[4]
    desc_col = cols[5]
    new_at = []
    extra_desc_prefix = []
    for w in at_col:
        left, right = _split_glued_time(w['text'])
        new_at.append(left)
        if right is not None:
            extra_desc_prefix.append(right)
    at_text = ' '.join(new_at).strip()
    desc_parts = extra_desc_prefix + [w['text'] for w in desc_col]
    desc_text = ' '.join(desc_parts).strip()

    out = {
        SPOT_HEADERS[0]: ' '.join(w['text'] for w in cols[0]).strip(),
        SPOT_HEADERS[1]: ' '.join(w['text'] for w in cols[1]).strip(),
        SPOT_HEADERS[2]: ' '.join(w['text'] for w in cols[2]).strip(),
        SPOT_HEADERS[3]: ' '.join(w['text'] for w in cols[3]).strip(),
        SPOT_HEADERS[4]: at_text,
        SPOT_HEADERS[5]: desc_text,
        SPOT_HEADERS[6]: ' '.join(w['text'] for w in cols[6]).strip(),
        SPOT_HEADERS[7]: ' '.join(w['text'] for w in cols[7]).strip(),
        SPOT_HEADERS[8]: ' '.join(w['text'] for w in cols[8]).strip(),
        SPOT_HEADERS[9]: ' '.join(w['text'] for w in cols[9]).strip(),
        SPOT_HEADERS[10]: ' '.join(w['text'] for w in cols[10]).strip(),
    }
    return out


def _make_table_node(node_id, headers, row_dicts, parent_id=None, note=""):
    rows = []
    for rd in row_dicts:
        row = []
        for h in headers:
            row.append({"key": h, "value": rd.get(h, "")})
        rows.append(row)
    return {
        "id": node_id,
        "type": "table",
        "content": {"headers": list(headers), "rows": rows},
        "relationship": {"parent_id": parent_id, "note": note},
    }


def _kv_node(node_id, pairs, parent_id=None, note=""):
    return {
        "id": node_id,
        "type": "key_value",
        "content": [{"key": k, "value": v} for k, v in pairs],
        "relationship": {"parent_id": parent_id, "note": note},
    }


def _meta_node(node_id, items, parent_id=None, note=""):
    return {
        "id": node_id,
        "type": "metadata",
        "content": list(items),
        "relationship": {"parent_id": parent_id, "note": note},
    }


def _split_first_sentence(text):
    """Return text up to the first sentence-ending period followed by space+capital."""
    m = re.search(r'([.!?])\s+[A-Z]', text)
    if m:
        return text[:m.start() + 1].strip()
    return text.strip()


def _parse_page(page, page_idx):
    record_id = f"r{page_idx + 1}"
    nodes = []

    words = page.extract_words(use_text_flow=False, x_tolerance=2, y_tolerance=2)
    rows = _cluster_lines(words, tol=2.5)

    # ---- Anchor positions ----
    y_property = None
    y_account_exec = None
    y_billing_addr = None
    y_send_payment = None
    y_lines_header = None
    y_powered_by = None

    for row in rows:
        for i, w in enumerate(row):
            if y_property is None and w['text'] == 'Property' and w['x0'] >= 300:
                y_property = w['top']
            if y_account_exec is None and w['text'] == 'Account' and w['x0'] >= 300:
                if i + 1 < len(row) and row[i + 1]['text'] == 'Executive':
                    y_account_exec = w['top']
            if y_billing_addr is None and w['text'] == 'Billing' and w['x0'] < 100:
                if i + 1 < len(row) and row[i + 1]['text'] == 'Address:':
                    y_billing_addr = w['top']
            if y_send_payment is None and w['text'] == 'Send' and w['x0'] < 100:
                if (i + 2 < len(row) and row[i + 1]['text'] == 'Payment'
                        and row[i + 2]['text'] == 'To:'):
                    y_send_payment = w['top']
            if y_powered_by is None and w['text'] == 'powered':
                if i + 1 < len(row) and row[i + 1]['text'] == 'by':
                    y_powered_by = w['top']
        if y_lines_header is None and len(row) >= 3 \
                and row[0]['text'] == 'Line' and row[0]['x0'] < 50 \
                and row[1]['text'] == 'Start' and row[2]['text'] == 'Date':
            y_lines_header = row[0]['top']

    if y_property is None: y_property = 40
    if y_account_exec is None: y_account_exec = 140
    if y_billing_addr is None: y_billing_addr = 148
    if y_send_payment is None: y_send_payment = 247
    if y_lines_header is None: y_lines_header = 360
    if y_powered_by is None: y_powered_by = page.height - 5

    # ---- Top metadata ----
    has_duplicate = _detect_duplicate_marker(page)
    top_meta = []
    for row in rows:
        if _row_min_y(row) >= y_property - 1:
            break
        text = _row_text(row).strip()
        if not text:
            continue
        if re.match(r'^Page\s+\d+\s+of\s+\d+$', text):
            top_meta.append(text)
            continue
        if 'DUPL' in text and text != 'DUPLICATE':
            # The watermark "DUPLICATE" overlaid on "INVOICE" produces a garbled
            # merge — emit both clean tokens and skip the original
            top_meta.append("DUPLICATE")
            top_meta.append("INVOICE")
            continue
        if text == 'INVOICE':
            top_meta.append("INVOICE")
            continue
        if text == 'DUPLICATE':
            top_meta.append("DUPLICATE")
            continue
        top_meta.append(text)

    # ---- n2: station block ----
    station_lines = []
    for row in rows:
        y = _row_min_y(row)
        if y < y_property - 1:
            continue
        if y >= y_billing_addr - 1:
            break
        left = [w for w in row if w['x0'] < 300]
        if not left:
            continue
        text = _row_text(left)
        if text:
            station_lines.append(text)

    station_kv_pairs = []
    if station_lines:
        station_kv_pairs.append(("Station", station_lines[0]))
        addr_lines = []
        idx = 1
        while idx < len(station_lines):
            ln = station_lines[idx]
            if (ln.startswith('Main:') or ln.startswith('Billing:')
                    or ln.lower().startswith('www.')
                    or ln.startswith('Affiliate')):
                break
            addr_lines.append(ln)
            idx += 1
        station_kv_pairs.append(("Address", ", ".join(addr_lines)))
        while idx < len(station_lines):
            ln = station_lines[idx]
            if ln.startswith('Main:'):
                station_kv_pairs.append(("Main", ln[len('Main:'):].strip()))
            elif ln.startswith('Billing:'):
                station_kv_pairs.append(("Billing", ln[len('Billing:'):].strip()))
            elif ln.lower().startswith('www.'):
                station_kv_pairs.append(("Website", ln.strip()))
            else:
                station_kv_pairs.append(("Affiliate", ln.strip()))
            idx += 1

    # ---- n3 + n4: right-column key-values ----
    n3_a_dict = {}
    n3_b_dict = {}
    n4_dict = {}
    n3_a_set = set(N3_A_KEYS)
    n3_b_set = set(N3_B_KEYS)
    for row in rows:
        y = _row_min_y(row)
        if y < y_property - 1:
            continue
        if y >= y_lines_header - 5:
            break
        right = [w for w in row if w['x0'] >= 300]
        if not right:
            continue
        is_n4_row = (y >= y_account_exec - 1)
        if not is_n4_row:
            a_keys = [w for w in row if 300 <= w['x0'] < 380]
            b_keys = [w for w in row if 459 <= w['x0'] < 510]
            a_key_text = ' '.join(w['text'] for w in a_keys).strip()
            b_key_text = ' '.join(w['text'] for w in b_keys).strip()
            b_known = b_key_text in n3_b_set
            if b_known:
                a_vals = [w for w in row if 380 <= w['x0'] < 459]
                b_vals = [w for w in row if w['x0'] >= 510]
                n3_b_dict[b_key_text] = ' '.join(w['text'] for w in b_vals).strip()
            else:
                a_vals = [w for w in row if 380 <= w['x0'] < 605]
            if a_key_text in n3_a_set:
                n3_a_dict[a_key_text] = ' '.join(w['text'] for w in a_vals).strip()
        else:
            keys = [w for w in row if 380 <= w['x0'] < 459]
            vals = [w for w in row if w['x0'] >= 459]
            key_text = ' '.join(w['text'] for w in keys).strip()
            val_text = ' '.join(w['text'] for w in vals).strip()
            if key_text in N4_KEY_SET:
                n4_dict[key_text] = val_text

    n3_pairs = []
    for k in N3_A_KEYS:
        n3_pairs.append((k, n3_a_dict.get(k, "")))
    for k in N3_B_KEYS:
        n3_pairs.append((k, n3_b_dict.get(k, "")))

    n4_pairs_ordered = [(k, n4_dict.get(k, "")) for k in N4_KEYS]

    # ---- n5: Billing Address ----
    n5_lines = []
    for row in rows:
        y = _row_min_y(row)
        if y < y_billing_addr + 1:
            continue
        if y >= y_send_payment - 1:
            break
        content = [w for w in row if 80 < w['x0'] < 300]
        if not content:
            continue
        text = _row_text(content)
        if text:
            n5_lines.append(text)
    billing_address_value = "\n".join(n5_lines)

    # ---- n6: Send Payment To (with Billing Inquiries) ----
    n6_lines = []
    billing_inquiries_value = None
    n6_terminator_prefixes = (
        'WO Payments', 'Quick Pay Link',
        'Effective ', 'This invoice', 'Standard Terms',
        'Non-Discrimination', 'You will be deemed', 'Class of Time',
    )
    last_y_in_n6 = None
    for row in rows:
        y = _row_min_y(row)
        if y < y_send_payment + 1:
            continue
        if y >= y_lines_header - 5:
            break
        content = [w for w in row if 18 <= w['x0'] < 300]
        if not content:
            continue
        text = _row_text(content)
        if not text:
            continue
        # Stop at banner / disclaimer rows
        if any(text.startswith(p) for p in n6_terminator_prefixes):
            break
        # gap detection (banner usually follows a y gap > 12)
        if last_y_in_n6 is not None and (y - last_y_in_n6) > 13:
            break
        if text.startswith('Billing Inquiries:'):
            billing_inquiries_value = text[len('Billing Inquiries:'):].strip()
            last_y_in_n6 = y
            break
        n6_lines.append(text)
        last_y_in_n6 = y
    send_payment_value = "\n".join(n6_lines)

    # ---- Mid-page metadata: rows between n6 area and lines header ----
    mid_meta = []
    for row in rows:
        y = _row_min_y(row)
        if y_send_payment is None:
            break
        if y < y_send_payment + 1:
            continue
        if y >= y_lines_header - 5:
            break
        text = _row_text(row).strip()
        if not text:
            continue
        if text.startswith('Billing Inquiries:'):
            continue
        # detect WO Payments-style banner that spans both columns
        xs = [w['x0'] for w in row]
        if xs and (max(xs) - min(xs) > 250) and text.startswith(('WO Payments', 'WO ', 'Quick Pay')):
            mid_meta.append(text)

    # ---- n7 + spots: lines table & spots tables ----
    line_dicts = []
    spots_per_line = []  # list of (line_index, list of row_dicts)
    current_spots = None
    last_line_row_idx = None
    last_line_y = None
    last_spot_y = None

    body_rows = [row for row in rows if _row_min_y(row) > y_lines_header + 1]
    body_rows.sort(key=lambda r: _row_min_y(r))

    for row in body_rows:
        y = _row_min_y(row)
        if y_powered_by and y >= y_powered_by - 1:
            break
        if not row:
            continue
        first = row[0]
        first_x = first['x0']
        first_t = first['text']

        if first_t == 'Spots/':
            continue
        if first_t == 'Class':
            # "Class of Time - Non Pre-emptible" is a sub-note attached to the
            # last line summary row's description.
            if last_line_row_idx is not None and current_spots is None:
                txt = _row_text(row).strip()
                cur = line_dicts[last_line_row_idx][LINE_HEADERS[3]]
                line_dicts[last_line_row_idx][LINE_HEADERS[3]] = (cur + '; ' + txt).strip('; ').strip()
            continue
        if first_t == 'Weeks:':
            continue
        if 80 <= first_x <= 100 and _is_date(first_t):
            continue
        if first_t == 'Spots:':
            current_spots = []
            spots_per_line.append((len(line_dicts) - 1, current_spots))
            continue
        # Line row
        if 25 <= first_x <= 42 and re.match(r'^\d+$', first_t):
            line_dicts.append(_parse_line_summary_row(row))
            current_spots = None
            last_line_row_idx = len(line_dicts) - 1
            last_line_y = y
            last_spot_y = None
            continue
        # Spots data row
        if 45 <= first_x <= 65 and re.match(r'^\d+$', first_t):
            if current_spots is not None:
                current_spots.append(_parse_spot_row(row))
                last_spot_y = y
            continue
        # Continuation row for description (only if very close to the line row)
        if (130 <= first_x <= 230 and len(row) <= 3
                and last_line_row_idx is not None and current_spots is None
                and last_line_y is not None and (y - last_line_y) < 12):
            for w in row:
                t = w['text']
                if len(t) == 1:
                    line_dicts[last_line_row_idx][LINE_HEADERS[3]] += t
                else:
                    cur = line_dicts[last_line_row_idx][LINE_HEADERS[3]]
                    line_dicts[last_line_row_idx][LINE_HEADERS[3]] = (cur + ' ' + t).strip()
            continue
        # otherwise ignore (likely footer text)

    # ---- Footer metadata ----
    # Determine y_after_data: y of last row in body that's a line/spot/spots-header
    last_data_y = y_lines_header
    for row in body_rows:
        y = _row_min_y(row)
        if not row:
            continue
        first_t = row[0]['text']
        first_x = row[0]['x0']
        if first_t in ('Spots:', 'Weeks:'):
            last_data_y = max(last_data_y, y)
        elif (25 <= first_x <= 65) and re.match(r'^\d+$', first_t):
            last_data_y = max(last_data_y, y)
        elif 80 <= first_x <= 100 and _is_date(first_t):
            last_data_y = max(last_data_y, y)
        elif first_t == 'Class':
            last_data_y = max(last_data_y, y)

    # Collect footer rows (y > last_data_y + 5)
    footer_lines = []  # list of (y, text)
    for row in rows:
        y = _row_min_y(row)
        if y <= last_data_y + 5:
            continue
        if y > y_powered_by + 2:
            break
        text = _row_text(row).strip()
        if not text:
            continue
        footer_lines.append((y, text))

    # Group footer lines into paragraphs by y-gap
    URL_RE = re.compile(r'https?://\S+')
    LABEL_RE = re.compile(r'^[A-Z][A-Za-z0-9\s\-]*?:\s')
    paragraphs = []  # list of list of (y, text)
    cur_para = []
    last_y = None
    for y, text in footer_lines:
        if last_y is not None and (y - last_y) > 11:
            if cur_para:
                paragraphs.append(cur_para)
                cur_para = []
        cur_para.append((y, text))
        last_y = y
    if cur_para:
        paragraphs.append(cur_para)

    footer_meta = []
    non_powered_idx = -1
    for para in paragraphs:
        text = ' '.join(t for _, t in para).strip()
        if not text:
            continue
        if text.lower().startswith('powered by'):
            footer_meta.append(text)
            continue
        non_powered_idx += 1
        is_first = (non_powered_idx == 0)
        has_label = bool(LABEL_RE.match(text))
        if not (is_first or has_label):
            continue
        # First sentence
        m = re.search(r'([.!?])\s+[A-Z]', text)
        if m:
            first_sent = text[:m.start() + 1].strip()
        else:
            first_sent = text.strip()
        # If URL is at the END of the first sentence, split it as a separate item.
        # Otherwise keep first sentence intact.
        url_match = URL_RE.search(first_sent)
        if url_match:
            url = url_match.group(0).rstrip('.,;:')
            after = first_sent[url_match.end():].strip()
            if not after:
                text_part = first_sent[:url_match.start()].strip()
                if text_part:
                    footer_meta.append(text_part)
                footer_meta.append(url)
            else:
                footer_meta.append(first_sent)
        else:
            footer_meta.append(first_sent)

    # ---- Assemble nodes ----
    meta_items = list(top_meta) + list(mid_meta) + list(footer_meta)

    nid = 1
    nodes.append(_meta_node(f"n{nid}", meta_items)); nid += 1

    if station_kv_pairs:
        nodes.append(_kv_node(f"n{nid}", station_kv_pairs)); nid += 1
    if n3_pairs:
        nodes.append(_kv_node(f"n{nid}", n3_pairs)); nid += 1
    if n4_pairs_ordered:
        nodes.append(_kv_node(f"n{nid}", n4_pairs_ordered)); nid += 1

    nodes.append(_kv_node(f"n{nid}", [("Billing Address", billing_address_value)])); nid += 1

    n6_pairs = [("Send Payment To", send_payment_value)]
    if billing_inquiries_value is not None:
        n6_pairs.append(("Billing Inquiries", billing_inquiries_value))
    nodes.append(_kv_node(f"n{nid}", n6_pairs)); nid += 1

    lines_node_id = f"n{nid}"
    nodes.append(_make_table_node(lines_node_id, LINE_HEADERS, line_dicts)); nid += 1

    # spots tables
    for line_idx, spot_rows in spots_per_line:
        if not spot_rows:
            continue
        if line_idx < 0 or line_idx >= len(line_dicts):
            note = "Spots aired"
        else:
            note = f"Spots aired for Line {line_idx + 1}"
        nodes.append(_make_table_node(
            f"n{nid}", SPOT_HEADERS, spot_rows,
            parent_id=lines_node_id, note=note,
        ))
        nid += 1

    return {"record_id": record_id, "nodes": nodes}


def extract(pdf_path):
    doc_name = os.path.splitext(os.path.basename(pdf_path))[0]
    out = {
        "doc_name": doc_name,
        "model": "code-extractor",
        "sampled_pages": 0,
        "records": [],
    }
    with pdfplumber.open(pdf_path) as pdf:
        out["sampled_pages"] = len(pdf.pages)
        for i, page in enumerate(pdf.pages):
            out["records"].append(_parse_page(page, i))
    return out
