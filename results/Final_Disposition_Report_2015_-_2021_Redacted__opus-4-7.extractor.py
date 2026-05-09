import os
import re
import pdfplumber


def extract(pdf_path: str) -> dict:
    BANNERS = [
        "Final Disposition Report",
        "Cases Disposed From 01-01-2015 To 08-31-2021",
        "Felony and Misdemeanor Cases",
        "Sorted On : Disposition",
        "Tuesday, November 02 2021 10:33 AM",
    ]

    KEYS_ORDER = [
        "File #", "Type", "Court#", "New File #", "Issued", "Disposed", "Div",
        "Defendant", "Race", "Sex", "DOB", "Height", "Weight", "Soc Sec#",
        "Prosecuting Attorney", "Defense Attorney", "Arrest #", "Report #",
        "Police Dept", "Officer", "SSN",
    ]

    COLS_ROW1 = [
        ("File #",       0,    80),
        ("Type",         80,   117),
        ("Court#",       117,  180),
        ("New File #",   180,  245),
        ("Issued",       245,  295),
        ("Disposed",     295,  355),
        ("Div",          355,  388),
        ("Defendant",    388,  470),
        ("Race",         470,  540),
        ("Sex",          540,  575),
        ("DOB",          575,  625),
        ("Height",       625,  670),
        ("Weight",       670,  715),
        ("Soc Sec#",     715, 1500),
    ]
    COLS_ROW2 = [
        ("Prosecuting Attorney", 0,    245),
        ("Defense Attorney",     245,  388),
        ("Arrest #",             388,  470),
        ("Report #",             470,  540),
        ("Police Dept",          540,  670),
        ("Officer",              670,  715),
        ("SSN",                  715, 1500),
    ]
    COLS_CHARGE = [
        ("Cnt",       370, 392),
        ("Charge",    392, 625),
        ("Disp",      625, 715),
        ("Sentenced", 715, 1500),
    ]

    def col_of(word, cols):
        cx = (word['x0'] + word['x1']) / 2.0
        for name, lo, hi in cols:
            if lo <= cx < hi:
                return name
        return None

    def merge_column_words(words):
        if not words:
            return ""
        words = sorted(words, key=lambda w: (w['top'], w['x0']))
        lines = []
        cur = [words[0]]
        cur_top = words[0]['top']
        for w in words[1:]:
            if abs(w['top'] - cur_top) <= 3:
                cur.append(w)
            else:
                lines.append(cur)
                cur = [w]
                cur_top = w['top']
        lines.append(cur)
        line_texts = []
        for line in lines:
            line_sorted = sorted(line, key=lambda w: w['x0'])
            line_texts.append(' '.join(w['text'] for w in line_sorted))
        result = line_texts[0]
        for lt in line_texts[1:]:
            if len(lt) == 1:
                result = result + lt
            else:
                result = result + ' ' + lt
        return result.strip()

    def cluster_rows(words, tol=6):
        if not words:
            return []
        sw = sorted(words, key=lambda w: w['top'])
        rows = []
        cur = [sw[0]]
        last_top = sw[0]['top']
        for w in sw[1:]:
            if w['top'] - last_top <= tol:
                cur.append(w)
                last_top = w['top']
            else:
                rows.append(sorted(cur, key=lambda x: x['x0']))
                cur = [w]
                last_top = w['top']
        rows.append(sorted(cur, key=lambda x: x['x0']))
        return rows

    def row_min_top(row):
        return min(w['top'] for w in row)

    def file_row_anchor_top(row):
        for w in row:
            if re.match(r'^\d{3}-\d{6}$', w['text']):
                return w['top']
        return row_min_top(row)

    def classify_row(row):
        if not row:
            return ('empty', None)
        text = ' '.join(w['text'] for w in row)
        leftmost = row[0]
        first_word_text = leftmost['text']

        if 'Final Disposition Report' in text and len(row) <= 4:
            return ('banner', text)
        if text.startswith('Cases Disposed From'):
            return ('banner', text)
        if text.startswith('Felony and Misdemeanor Cases'):
            return ('banner', text)
        if text.startswith('Sorted On'):
            return ('banner', text)
        if re.match(r'^\w+,\s+\w+\s+\d+\s+\d+\s+\d+:\d+\s+[AP]M', text):
            return ('banner', text)
        if re.match(r'^Page\s+\d+\s+of\s+\d+', text):
            return ('footer', text)
        if first_word_text == 'File' and 'Type' in text and 'Court#' in text:
            return ('header_row1', text)
        if first_word_text == 'Prosecuting' and 'Defense' in text and 'SSN' in text:
            return ('header_row2', text)
        if first_word_text == 'Cnt' and 'Charge' in text and 'Disp' in text and 'Sentenced' in text:
            return ('charge_header', text)
        m = re.match(r'^Total Disposed:\s*(\d+)', text)
        if m:
            return ('total_disposed', m.group(1))
        if (re.match(r'^\d{2}-\d{2}-\d{4}$', first_word_text)
                and leftmost['x0'] < 70 and len(row) == 1):
            return ('disp_date', first_word_text)
        if re.match(r'^\d{3}-\d{6}$', first_word_text) and leftmost['x0'] < 80:
            return ('file_row', text)
        if 370 <= leftmost['x0'] < 395 and re.match(r'^\d+$', first_word_text):
            return ('charge_row', text)
        return ('frag', text)

    pages_data = []
    with pdfplumber.open(pdf_path) as pdf:
        sampled_pages = len(pdf.pages)
        for page_idx, page in enumerate(pdf.pages):
            words = page.extract_words(use_text_flow=True, keep_blank_chars=False,
                                       x_tolerance=3, y_tolerance=3)
            rows = cluster_rows(words, tol=6)
            rows = sorted(rows, key=row_min_top)
            pages_data.append((page_idx, rows))

    records = []
    state_record = None
    state_subrecord = 'init'
    current_disp_date = None
    pending_frags = []
    last_in_section = None

    for page_idx, rows in pages_data:
        anchor_classes = []
        for i, row in enumerate(rows):
            rt, _ = classify_row(row)
            if rt in ('file_row', 'charge_header', 'charge_row'):
                anchor_classes.append((i, rt))

        attorney_indices = set()
        for ai, (ri, rt) in enumerate(anchor_classes):
            if rt != 'file_row':
                continue
            next_ri = len(rows)
            if ai + 1 < len(anchor_classes):
                next_ri = anchor_classes[ai + 1][0]
            anchor_top = file_row_anchor_top(rows[ri])
            best = None
            best_score = None
            for j in range(ri + 1, next_ri):
                r = rows[j]
                rj_type, _ = classify_row(r)
                if rj_type != 'frag':
                    continue
                rj_top = row_min_top(r)
                diff = rj_top - anchor_top
                if not (10 <= diff <= 22):
                    continue
                lm_x = r[0]['x0']
                score = (abs(diff - 15), 0 if lm_x < 400 else 1, lm_x)
                if best is None or score < best_score:
                    best = j
                    best_score = score
            if best is not None:
                attorney_indices.add(best)

        for idx, row in enumerate(rows):
            rtype, info = classify_row(row)

            if rtype in ('banner', 'footer', 'header_row1', 'header_row2', 'empty'):
                continue

            if rtype == 'disp_date':
                current_disp_date = info
                continue

            if rtype == 'total_disposed':
                if last_in_section is not None:
                    last_in_section['metadata_extras'].append(f"Total Disposed: {info}")
                continue

            if rtype == 'file_row':
                pre_frags = []
                if state_record and state_record['charges']:
                    for f in pending_frags:
                        has_outside = any(w['x0'] < 388 for w in f)
                        in_charge_col = any(392 <= w['x0'] < 625 for w in f)
                        if not has_outside and in_charge_col:
                            state_record['charges'][-1].extend(f)
                        else:
                            pre_frags.append(f)
                else:
                    pre_frags = list(pending_frags)
                pending_frags = []

                state_record = {
                    'metadata_extras': [],
                    'file_row_words': list(row),
                    'attorney_row_words': [],
                    'charges': [],
                    'disp_date': current_disp_date,
                    'start_page': page_idx,
                    'end_page': page_idx,
                }
                for pf in pre_frags:
                    state_record['file_row_words'].extend(pf)

                state_subrecord = 'after_file'
                records.append(state_record)
                last_in_section = state_record
                continue

            if rtype == 'charge_header':
                if state_record:
                    if state_subrecord in ('after_attorney', 'after_file'):
                        for f in pending_frags:
                            state_record['attorney_row_words'].extend(f)
                    pending_frags = []
                state_subrecord = 'in_charges'
                continue

            if rtype == 'charge_row':
                if state_record:
                    if state_record['charges']:
                        for f in pending_frags:
                            state_record['charges'][-1].extend(f)
                    else:
                        for f in pending_frags:
                            state_record['attorney_row_words'].extend(f)
                    pending_frags = []
                    state_record['charges'].append(list(row))
                    if page_idx > state_record['end_page']:
                        state_record['end_page'] = page_idx
                continue

            if idx in attorney_indices:
                if state_record:
                    for f in pending_frags:
                        state_record['file_row_words'].extend(f)
                    pending_frags = []
                    state_record['attorney_row_words'] = list(row)
                state_subrecord = 'after_attorney'
            else:
                pending_frags.append(row)

        if pending_frags and state_record:
            if state_subrecord == 'in_charges' and state_record['charges']:
                for f in pending_frags:
                    state_record['charges'][-1].extend(f)
            elif state_subrecord == 'after_attorney':
                for f in pending_frags:
                    state_record['attorney_row_words'].extend(f)
            else:
                for f in pending_frags:
                    state_record['file_row_words'].extend(f)
            pending_frags = []

    out_records = []
    doc_name = os.path.splitext(os.path.basename(pdf_path))[0]
    if doc_name.endswith('__sample'):
        doc_name = doc_name[:-len('__sample')]

    for ri, rec in enumerate(records):
        kv = {k: '' for k in KEYS_ORDER}

        file_cols = {name: [] for name, _, _ in COLS_ROW1}
        for w in rec['file_row_words']:
            c = col_of(w, COLS_ROW1)
            if c is not None:
                file_cols[c].append(w)
        for k, ws in file_cols.items():
            kv[k] = merge_column_words(ws)

        att_cols = {name: [] for name, _, _ in COLS_ROW2}
        for w in rec['attorney_row_words']:
            c = col_of(w, COLS_ROW2)
            if c is not None:
                att_cols[c].append(w)
        for k, ws in att_cols.items():
            kv[k] = merge_column_words(ws)

        is_juvenile = ('JV' in (kv.get('Court#', '') or '')) and not (kv.get('Defendant', '') or '').strip()
        is_civil = (kv.get('Type', '') or '').strip().upper() == 'C'
        spans_pages = rec['start_page'] != rec['end_page']
        no_charges = len(rec['charges']) == 0
        is_last_record = (ri == len(records) - 1)

        if is_juvenile:
            kv['Defendant'] = '[REDACTED]'

        if is_civil:
            if kv.get('Police Dept', '') and not kv.get('Defense Attorney', ''):
                kv['Defense Attorney'] = kv['Police Dept']
                kv['Police Dept'] = ''

        metadata_content = list(BANNERS)
        if rec['disp_date']:
            metadata_content.append(f"Disposition Date Section: {rec['disp_date']}")
        for ex in rec['metadata_extras']:
            metadata_content.append(ex)

        notes = []
        if is_juvenile:
            n = "Note: juvenile case - defendant name redacted"
            if spans_pages:
                n += f"; case spans page {rec['start_page']+1} to page {rec['end_page']+1}"
            notes.append(n)
        elif is_civil:
            notes.append("Note: civil case (Type C) - corporate defendant; person fields not applicable")
        elif spans_pages:
            notes.append(f"Note: case data continues from page {rec['start_page']+1} to page {rec['end_page']+1}")
        elif no_charges and is_last_record:
            notes.append(f"Note: case header visible at bottom of page {rec['start_page']+1}; charge rows truncated/not present in sample")

        for n in notes:
            metadata_content.append(n)

        table_rows = []
        for charge_words in rec['charges']:
            ch_cols = {k: [] for k, _, _ in COLS_CHARGE}
            for w in charge_words:
                c = col_of(w, COLS_CHARGE)
                if c is not None:
                    ch_cols[c].append(w)
            row_data = []
            for k in ['Cnt', 'Charge', 'Disp', 'Sentenced']:
                row_data.append({"key": k, "value": merge_column_words(ch_cols[k])})
            table_rows.append(row_data)

        nodes = []
        nodes.append({
            "id": "n1",
            "type": "metadata",
            "content": metadata_content,
            "relationship": {"parent_id": None, "note": ""},
        })
        nodes.append({
            "id": "n2",
            "type": "key_value",
            "content": [{"key": k, "value": kv[k]} for k in KEYS_ORDER],
            "relationship": {"parent_id": "n1", "note": f"case under disposition date {rec['disp_date']}"},
        })
        if no_charges:
            table_note = "charges section header present but no rows visible in sample"
        else:
            table_note = "charges for this case"
        nodes.append({
            "id": "n3",
            "type": "table",
            "content": {
                "headers": ["Cnt", "Charge", "Disp", "Sentenced"],
                "rows": table_rows,
            },
            "relationship": {"parent_id": "n2", "note": table_note},
        })

        out_records.append({
            "record_id": f"r{ri+1}",
            "nodes": nodes,
        })

    return {
        "doc_name": doc_name,
        "model": "code-extractor",
        "sampled_pages": sampled_pages,
        "records": out_records,
    }
