"""
TWIX Error Detection Module
Validates extraction outputs using GPT-4o Vision by comparing against original PDFs
"""

import json
import os
import tempfile
from typing import Dict, List, Any
from pdf2image import convert_from_path
from . import cost
from .model import model

TEXT_MODEL = 'gpt-4o'

# Image conversion settings
IMAGE_DPI = 300  # Higher DPI = better OCR accuracy but larger files
JPEG_QUALITY = 95  # JPEG compression quality (1-100)
ESTIMATED_TOKENS_PER_IMAGE = 1200  # Approximate token count per image for vision models


def detect_errors(extraction_output: Dict[str, Any],
                 pdf_path: str,
                 max_pages: int = 2,
                 max_records: int = 2,
                 vision_model: str = 'vision-claude-sonnet') -> Dict[str, Any]:
    """
    Detect extraction errors by comparing output against original PDF

    Args:
        extraction_output: TWIX extraction output (dict of filename -> records)
        pdf_path: Path to the original PDF file
        max_pages: Maximum PDF pages to analyze
        max_records: Maximum records to validate per file
        vision_model: Vision model to use ('vision-claude-sonnet' or 'vision-gpt-4o')

    Returns:
        Dict with 'errors' (list), 'error_count' (int), 'cost' (float)
    """
    # Convert PDF to images
    temp_images = _pdf_to_images(pdf_path, max_pages)
    if not temp_images:
        return {'errors': [], 'error_count': 0, 'cost': 0, 'error': 'PDF conversion failed'}

    try:
        # Sample records
        sample_data = _sample_extraction(extraction_output, max_records)

        # Build prompt
        prompt = _build_prompt(sample_data)

        # Call vision model
        print(f"🔍 Analyzing {len(temp_images)} PDF page(s) with {vision_model}...")
        response = model(vision_model, prompt, temp_images)

        # Calculate cost
        vision_tokens = len(temp_images) * ESTIMATED_TOKENS_PER_IMAGE
        text_tokens = cost.count_tokens(prompt, TEXT_MODEL)
        output_tokens = cost.count_tokens(response, TEXT_MODEL)
        total_cost = cost.cost(TEXT_MODEL, text_tokens + vision_tokens, output_tokens)

        # Parse response
        errors = _parse_response(response)

        print(f"✓ Found {len(errors)} error(s) | Cost: ${total_cost:.4f}")

        return {
            'errors': errors,
            'error_count': len(errors),
            'cost': total_cost
        }

    except Exception as e:
        print(f"✗ Error detection failed: {e}")
        return {'errors': [], 'error_count': 0, 'cost': 0, 'error': str(e)}

    finally:
        _cleanup_images(temp_images)


def _pdf_to_images(pdf_path: str, max_pages: int) -> List[str]:
    """Convert PDF pages to temporary image files"""
    try:
        images = convert_from_path(pdf_path, first_page=1, last_page=max_pages, dpi=IMAGE_DPI)
        temp_paths = []

        for i, img in enumerate(images):
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.jpg')
            img.save(temp_file.name, format="JPEG", quality=JPEG_QUALITY)
            temp_paths.append(temp_file.name)
            temp_file.close()

        return temp_paths
    except Exception as e:
        print(f"PDF conversion error: {e}")
        return []


def _cleanup_images(image_paths: List[str]) -> None:
    """Delete temporary image files"""
    for path in image_paths:
        try:
            if os.path.exists(path):
                os.remove(path)
        except Exception:
            pass


def _sample_extraction(extraction_output: Dict, max_records: int) -> Dict:
    """Sample first N records from extraction output"""
    return {
        filename: records[:max_records]
        for filename, records in extraction_output.items()
        if isinstance(records, list)
    }


def _build_prompt(sample_data: Dict) -> str:
    """Build validation prompt for vision model"""
    data_json = json.dumps(sample_data, indent=2)

    prompt = f"""Compare this extracted data against the PDF images and identify any errors.

EXTRACTED DATA:
{data_json}

ERROR TYPES:

1. VALUE_MISSING
   - Field exists with value="missing", but readable data IS visible in the PDF
   - NOT an error if PDF shows: [REDACTED], (Not Provided), (N/A), blank spaces, black boxes, or any redaction
   - Example: {{"field": "SSN", "current_value": "missing", "expected_value": "123-45-6789"}}

2. VALUE_WRONG
   - Field exists with a value, but the value is incorrect compared to the PDF
   - This includes incomplete values, truncated text, wrong numbers, wrong names, etc.
   - Example: {{"field": "Amount", "current_value": "$559.98", "expected_value": "$2,196.34"}}
   - Example: {{"field": "Title", "current_value": "Bridging the Gap", "expected_value": "Bridging the Gap: Complete Title Here"}}

3. FIELD_MISSING
   - An important field visible in the PDF is completely absent from the extracted data
   - The field key itself doesn't exist in the extraction output
   - Example: PDF has "Date of Birth" but extraction has no "date_of_birth" or similar field

4. FIELD_WRONG
   - The field name/label is incorrect compared to the PDF
   - Example: PDF shows "Date of Birth" but extraction has "Birth_Date"
   - Example: {{"field": "Birth_Date", "current_value": "Birth_Date", "expected_value": "Date_of_Birth"}}

5. MAPPING_ERROR
   - A value is placed under the wrong field name
   - The field name doesn't match what the value represents
   - Example: Date value "2024-01-15" appears in a "Name" field
   - Example: Dollar amount "$5,000" appears in a "Description" field
   - NOT a mapping error if the field name is correct but the value is just wrong/incomplete

VALIDATION RULES:
- Only validate field keys and values that exist in the extracted data
- Ignore PDF text that is not part of the extracted fields
- value="missing" + redacted/blank PDF = NOT AN ERROR
- value="missing" + readable PDF data = VALUE_MISSING error
- Incomplete or truncated values = VALUE_WRONG (not MAPPING_ERROR)
- Wrong field entirely = MAPPING_ERROR
- Ignore minor formatting differences and typos

OUTPUT FORMAT:
Return ONLY a JSON array (no markdown, no code blocks):
[{{"error_type":"VALUE_WRONG","field":"Amount","current_value":"$559.98","expected_value":"$2,196.34","location":"Page 1, row 20"}},
 {{"error_type":"FIELD_WRONG","field":"Birth_Date","current_value":"Birth_Date","expected_value":"Date_of_Birth","location":"Page 1"}}]

Return [] if no errors found."""

    return prompt


def _parse_response(response: str) -> List[Dict]:
    """Parse JSON array from model response"""
    response = response.strip()

    # Extract JSON from markdown code blocks if present
    if '```' in response:
        start = response.find('[')
        end = response.rfind(']') + 1
        if start != -1 and end > 0:
            response = response[start:end]

    try:
        errors = json.loads(response)
        return errors if isinstance(errors, list) else []
    except json.JSONDecodeError:
        return []
