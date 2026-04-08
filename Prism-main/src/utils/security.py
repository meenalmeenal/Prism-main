# src/utils/security.py
import re
from typing import Dict, Optional, Pattern, List
import logging

logger = logging.getLogger(__name__)

class PIIScanner:
    """Scans and masks PII in text."""
    
    def __init__(self):
        self.patterns: Dict[str, Pattern] = {
            'email': re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'),
            'phone': re.compile(r'\b(?:\+?(\d{1,3}))?[-. (]*(\d{3})[-. )]*(\d{3})[-. ]*(\d{4})\b'),
            'ip': re.compile(r'\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b'),
            'ssn': re.compile(r'\b\d{3}[-.]?\d{2}[-.]?\d{4}\b')
        }
        
        self.mask_map = {
            'email': '<EMAIL_REDACTED>',
            'phone': '<PHONE_REDACTED>',
            'ip': '<IP_REDACTED>',
            'ssn': '<SSN_REDACTED>'
        }
    
    def find_pii(self, text: str) -> Dict[str, List[str]]:
        """Find all PII in the given text."""
        found = {}
        for pii_type, pattern in self.patterns.items():
            matches = pattern.findall(text)
            if matches:
                found[pii_type] = list(set(matches))
        return found
    
    def mask_pii(self, text: str) -> str:
        """Mask all PII in the given text."""
        masked_text = text
        for pii_type, pattern in self.patterns.items():
            masked_text = pattern.sub(self.mask_map[pii_type], masked_text)
        return masked_text

# Singleton instance
pii_scanner = PIIScanner()