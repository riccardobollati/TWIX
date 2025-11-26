"""
TWIX Visualization Module
Display extracted data in readable formats for Jupyter notebooks
"""

from typing import Dict, List, Any, Optional
import pandas as pd
from IPython.display import display, HTML
import json


def visualize_extraction(extraction_output: Dict[str, Any],
                        max_records: Optional[int] = None,
                        record_ids: Optional[List[int]] = None,
                        show_structure: bool = False) -> None:
    """
    Visualize TWIX extraction output in Jupyter notebooks

    Args:
        extraction_output: TWIX extraction output (dict of filename -> records)
        max_records: Maximum number of records to display (default: all)
        record_ids: Specific record IDs to display (default: None)
        show_structure: Show nested structure as formatted JSON (default: False)

    Usage:
        import twix
        twix.visualize_extraction(extraction_output, max_records=5)
    """

    for filename, records in extraction_output.items():
        print(f"\n{'='*80}")
        print(f"FILE: {filename}")
        print(f"TOTAL RECORDS: {len(records)}")
        print(f"{'='*80}\n")

        # Filter records
        if record_ids is not None:
            records = [r for r in records if r.get('id') in record_ids]
        elif max_records is not None:
            records = records[:max_records]

        for record in records:
            _visualize_record(record, show_structure)


def _visualize_record(record: Dict, show_structure: bool = False) -> None:
    """Visualize a single record"""

    record_id = record.get('id', 'N/A')
    print(f"\n{'─'*80}")
    print(f"RECORD ID: {record_id}")
    print(f"{'─'*80}")

    if show_structure:
        # Show full JSON structure
        print(json.dumps(record, indent=2))
        return

    content = record.get('content', [])

    for idx, section in enumerate(content):
        section_type = section.get('type', 'unknown')
        section_content = section.get('content', [])

        if section_type == 'table':
            _display_table(section_content, f"Table {idx+1}")
        elif section_type == 'kv':
            _display_kv(section_content, f"Key-Value {idx+1}")
        else:
            print(f"\n[{section_type.upper()}]")
            print(json.dumps(section_content, indent=2))


def _display_table(content: List[Dict], title: str) -> None:
    """Display table content as pandas DataFrame"""

    if not content:
        print(f"\n[{title}] - Empty")
        return

    print(f"\n[{title}]")

    try:
        df = pd.DataFrame(content)
        display(df)
    except Exception as e:
        # Fallback to simple display
        print(json.dumps(content, indent=2))


def _display_kv(content: List[Dict], title: str) -> None:
    """Display key-value content in a readable format"""

    if not content:
        print(f"\n[{title}] - Empty")
        return

    print(f"\n[{title}]")

    # Flatten list of single-key dicts into one dict
    kv_dict = {}
    for item in content:
        if isinstance(item, dict):
            kv_dict.update(item)

    # Display as DataFrame for better formatting
    try:
        df = pd.DataFrame([kv_dict])
        display(df.T.rename(columns={0: 'Value'}))
    except Exception:
        # Fallback to simple key-value pairs
        for key, value in kv_dict.items():
            print(f"  {key}: {value}")


def flatten_to_dataframe(extraction_output: Dict[str, Any],
                         max_records: Optional[int] = None) -> pd.DataFrame:
    """
    Flatten TWIX extraction output to a single pandas DataFrame

    Args:
        extraction_output: TWIX extraction output
        max_records: Maximum records to include (default: all)

    Returns:
        pandas DataFrame with flattened records

    Usage:
        df = twix.flatten_to_dataframe(extraction_output)
        df.head()
    """

    rows = []

    for filename, records in extraction_output.items():
        if max_records:
            records = records[:max_records]

        for record in records:
            row = {'filename': filename, 'record_id': record.get('id')}

            # Extract all fields from content
            content = record.get('content', [])
            for section in content:
                section_content = section.get('content', [])

                if isinstance(section_content, list):
                    for item in section_content:
                        if isinstance(item, dict):
                            # Flatten all key-value pairs
                            for key, value in item.items():
                                # Handle duplicate keys by numbering them
                                original_key = key
                                counter = 1
                                while key in row:
                                    key = f"{original_key}_{counter}"
                                    counter += 1
                                row[key] = value

            rows.append(row)

    return pd.DataFrame(rows)


def compare_with_errors(extraction_output: Dict[str, Any],
                       error_report: Dict[str, Any],
                       record_ids: Optional[List[int]] = None) -> None:
    """
    Visualize extraction data alongside detected errors

    Args:
        extraction_output: TWIX extraction output
        error_report: Output from twix.detect_errors()
        record_ids: Specific record IDs to display (default: uses sampled records)

    Usage:
        error_report = twix.detect_errors(extraction_output, pdf_path)
        twix.compare_with_errors(extraction_output, error_report)
    """

    errors = error_report.get('errors', [])

    if not errors:
        print("✓ No errors found!")
        return

    print(f"\n{'='*80}")
    print(f"ERROR COMPARISON VIEW")
    print(f"Total Errors: {len(errors)}")
    print(f"{'='*80}\n")

    # Group errors by field
    error_by_field = {}
    for error in errors:
        field = error.get('field', 'Unknown')
        if field not in error_by_field:
            error_by_field[field] = []
        error_by_field[field].append(error)

    # Display errors grouped by field
    for field, field_errors in error_by_field.items():
        print(f"\n{'─'*80}")
        print(f"FIELD: {field}")
        print(f"{'─'*80}")

        for error in field_errors:
            error_type = error.get('error_type', 'UNKNOWN')
            current = error.get('current_value', 'N/A')
            expected = error.get('expected_value', 'N/A')
            location = error.get('location', 'N/A')

            print(f"\n  Error Type: {error_type}")
            print(f"  Current:    {current}")
            print(f"  Expected:   {expected}")
            print(f"  Location:   {location}")

    # Show extraction data for context
    print(f"\n{'='*80}")
    print(f"EXTRACTED DATA (for context)")
    print(f"{'='*80}")
    visualize_extraction(extraction_output, max_records=3, record_ids=record_ids)
