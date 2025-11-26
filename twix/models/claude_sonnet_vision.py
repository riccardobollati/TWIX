import anthropic
import base64
import os

_client = None

def _get_client():
    """Lazy initialization of Anthropic client"""
    global _client
    if _client is None:
        api_key = os.getenv('ANTHROPIC_API_KEY')
        if not api_key:
            raise ValueError(
                "ANTHROPIC_API_KEY environment variable not set. "
                "Please set it with: os.environ['ANTHROPIC_API_KEY'] = 'your-key'"
            )
        # Strip whitespace and ensure non-empty
        api_key = api_key.strip()
        if not api_key:
            raise ValueError(
                "ANTHROPIC_API_KEY environment variable is empty. "
                "Please set it with: os.environ['ANTHROPIC_API_KEY'] = 'your-key'"
            )
        # Initialize client with explicit api_key parameter
        _client = anthropic.Anthropic(api_key=api_key)
    return _client


def encode_image(image_path):
    """Encode image to base64"""
    with open(image_path, 'rb') as image_file:
        return base64.b64encode(image_file.read()).decode('utf-8')


def get_image_media_type(image_path):
    """Determine media type from file extension"""
    ext = image_path.lower().split('.')[-1]
    if ext in ['jpg', 'jpeg']:
        return 'image/jpeg'
    elif ext == 'png':
        return 'image/png'
    elif ext == 'gif':
        return 'image/gif'
    elif ext == 'webp':
        return 'image/webp'
    else:
        return 'image/jpeg'  # default


def claude_sonnet_vision(image_paths, prompt):
    """
    Call Claude 4.5 Sonnet with vision capabilities

    Args:
        image_paths: List of paths to image files
        prompt: Text prompt

    Returns:
        String response from Claude
    """
    # Build content array with images first, then text
    content = []

    # Add all images to content
    for image_path in image_paths:
        image_data = encode_image(image_path)
        media_type = get_image_media_type(image_path)

        content.append({
            'type': 'image',
            'source': {
                'type': 'base64',
                'media_type': media_type,
                'data': image_data
            }
        })

    # Add text prompt after images
    content.append({
        'type': 'text',
        'text': prompt
    })

    client = _get_client()
    response = client.messages.create(
        model='claude-sonnet-4-5-20250929',
        max_tokens=4096,
        messages=[
            {
                'role': 'user',
                'content': content
            }
        ]
    )

    return response.content[0].text
