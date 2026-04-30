import re

PII_PATTERNS = [
    (r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', '[EMAIL]'),
    (r'\b\d{3}[-.\s]?\d{3}[-.\s]?\d{4}\b', '[PHONE]'),
    (r'\b\d{3}-\d{2}-\d{4}\b', '[SSN]'),
    (r'\b4[0-9]{12}(?:[0-9]{3})?\b', '[CARD]'),
    (r'\b(?:password|passwd|pwd)\s*[:=]\s*\S+', '[PASSWORD]'),
    (r'\b(?:token|api_key|secret)\s*[:=]\s*\S+', '[SECRET]'),
    (r'\bhttps?://[^\s]+', '[URL]'),
    (r'\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b', '[IP]'),
]

def mask_pii(text: str) -> str:
    """Mask PII from text before sending to AI."""
    if not text:
        return text
    for pattern, replacement in PII_PATTERNS:
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    return text