"""PII Masking and Sanitization Module for AI Test Generation.

Hardened PII Masker detecting:
- Multi-brand Credit Cards (Visa, Mastercard, Amex, Discover, JCB, Diners, Maestro) + Luhn validation
- Email addresses
- Phone numbers (E.164, IN, US formats)
- SSN, PAN, Aadhaar, IBAN
- Contextual Date of Birth (DOB)
- Postal addresses
- Person names (NER-lite with domain terms allowlist)
- URLs (smart, strict, off modes)
- Passwords, Secrets, API keys, IP addresses
"""

from __future__ import annotations

import os
import re
import urllib.parse
from typing import Dict, List, Optional, Tuple

# Domain allowlist: domain keywords, technical tools, Jira/Zephyr/Playwright terms, ticket keys
DOMAIN_ALLOWLIST = {
    "jira",
    "zephyr",
    "zephyr scale",
    "scale",
    "playwright",
    "cypress",
    "nightwatch",
    "cucumber",
    "selenium",
    "login",
    "page",
    "login page",
    "dashboard",
    "test",
    "case",
    "test case",
    "acceptance",
    "criteria",
    "acceptance criteria",
    "api",
    "spec",
    "api spec",
    "step",
    "summary",
    "report",
    "feature",
    "story",
    "bug",
    "task",
    "epic",
    "sprint",
    "positive",
    "negative",
    "boundary",
    "risk",
    "risk based",
    "ui validation",
    "admin",
    "guest",
    "user",
    "customer",
    "mock",
    "null",
    "none",
    "true",
    "false",
}

# Optional spacy loader
_SPACY_NLP = None
try:
    import spacy
    try:
        _SPACY_NLP = spacy.load("en_core_web_sm")
    except Exception:
        _SPACY_NLP = None
except ImportError:
    _SPACY_NLP = None


def luhn_checksum(number_str: str) -> bool:
    """Validate number string using Luhn algorithm."""
    digits = [int(c) for c in number_str if c.isdigit()]
    if len(digits) < 13 or len(digits) > 19:
        return False
    checksum = 0
    reverse_digits = digits[::-1]
    for i, d in enumerate(reverse_digits):
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        checksum += d
    return checksum % 10 == 0


def _is_card_candidate(clean_digits: str) -> bool:
    """Check if digits match known card brand prefixes."""
    # Visa: 4
    if clean_digits.startswith("4") and len(clean_digits) in {13, 16, 19}:
        return True
    # Mastercard: 51-55 or 2221-2720
    if len(clean_digits) == 16:
        if 51 <= int(clean_digits[:2]) <= 55:
            return True
        if 2221 <= int(clean_digits[:4]) <= 2720:
            return True
    # Amex: 34 or 37 (15 digits)
    if clean_digits.startswith(("34", "37")) and len(clean_digits) == 15:
        return True
    # Discover: 6011, 65, 644-649, 622 (16 digits)
    if len(clean_digits) == 16 and (
        clean_digits.startswith(("6011", "65"))
        or (644 <= int(clean_digits[:3]) <= 649)
        or (622 <= int(clean_digits[:3]) <= 622)
    ):
        return True
    # Diners Club: 300-305, 36, 38 (14 digits)
    if len(clean_digits) == 14 and (
        (300 <= int(clean_digits[:3]) <= 305) or clean_digits.startswith(("36", "38"))
    ):
        return True
    # JCB: 3528-3589 or 2131/1800 (15 or 16 digits)
    if len(clean_digits) in {15, 16} and (
        (3528 <= int(clean_digits[:4]) <= 3589) or clean_digits.startswith(("2131", "1800"))
    ):
        return True
    # Maestro: 5018, 5020, 5038, 58, 6304, 6759, 6761, 6762, 6763 (12-19 digits)
    if (
        clean_digits.startswith(
            ("5018", "5020", "5038", "58", "6304", "6759", "6761", "6762", "6763")
        )
        and 12 <= len(clean_digits) <= 19
    ):
        return True
    return False


IBAN_COUNTRY_LENGTHS = {
    "AL": 28, "AD": 24, "AT": 20, "BE": 16, "BA": 20, "BG": 22, "HR": 21, "CY": 28,
    "CZ": 24, "DK": 18, "EE": 20, "FI": 18, "FR": 27, "DE": 22, "GR": 27, "HU": 28,
    "IS": 26, "IE": 22, "IL": 23, "IT": 27, "LV": 21, "LT": 20, "LU": 20, "MT": 31,
    "NL": 18, "NO": 15, "PL": 28, "PT": 25, "RO": 24, "SA": 24, "RS": 22, "SK": 24,
    "SI": 19, "ES": 24, "SE": 24, "CH": 21, "TN": 24, "TR": 26, "AE": 23, "GB": 22,
}


def _redact_url_smart(url_str: str) -> str:
    """Smart URL redaction: keep scheme, host, path; redact userinfo and sensitive query values."""
    try:
        parsed = urllib.parse.urlsplit(url_str)
        netloc = parsed.netloc
        if "@" in netloc:
            _, host = netloc.split("@", 1)
            netloc = f"[REDACTED_USERINFO]@{host}"

        query = parsed.query
        if query:
            sensitive_keys = {
                "token", "auth", "key", "password", "session",
                "email", "user", "api_key", "access_token", "sig", "secret",
            }
            q_pairs = urllib.parse.parse_qsl(query, keep_blank_values=True)
            redacted_pairs = []
            for k, v in q_pairs:
                if k.lower() in sensitive_keys:
                    redacted_pairs.append((k, "[REDACTED]"))
                else:
                    redacted_pairs.append((k, v))
            query = urllib.parse.urlencode(redacted_pairs, safe="[]")

        return urllib.parse.urlunsplit((parsed.scheme, netloc, parsed.path, query, parsed.fragment))
    except Exception:
        return "[URL]"


class PIIMasker:
    """Hardened PII Masker with multiple detectors, configurable URL mode, and audit summary."""

    def __init__(self, url_mode: Optional[str] = None):
        self.url_mode = (
            url_mode or os.getenv("PII_URL_MASK_MODE", "smart")
        ).strip().lower()

    def mask_with_summary(self, text: str) -> Tuple[str, Dict[str, int]]:
        """Mask PII in text and return both the masked text and detection summary counts."""
        if not text:
            return text, {}

        summary: Dict[str, int] = {
            "card": 0,
            "email": 0,
            "phone": 0,
            "ssn": 0,
            "pan": 0,
            "aadhaar": 0,
            "iban": 0,
            "dob": 0,
            "address": 0,
            "name": 0,
            "password": 0,
            "secret": 0,
            "ip": 0,
            "url": 0,
        }

        # 1. URLs (smart, strict, off) — run first to prevent url tokens being mangled by secret/password/address regexes
        if self.url_mode != "off":
            def _mask_url(match):
                summary["url"] += 1
                if self.url_mode == "strict":
                    return "[URL]"
                return _redact_url_smart(match.group(0))

            text = re.sub(r'https?://[^\s<>"\'{}|\\^`]+', _mask_url, text)

        # 2. Passwords, Secrets, Tokens (explicit key-value pairs not inside URLs or already redacted)
        def _mask_password(match):
            summary["password"] += 1
            return match.group(0).split("=")[0].split(":")[0] + ": [PASSWORD]"

        text = re.sub(r'(?<![?&])\b(?:password|passwd|pwd)\s*[:=]\s*(?!\[PASSWORD\])[^\s&,;]+', _mask_password, text, flags=re.IGNORECASE)

        def _mask_secret(match):
            summary["secret"] += 1
            return match.group(0).split("=")[0].split(":")[0] + ": [SECRET]"

        text = re.sub(r'(?<![?&])\b(?:token|api_key|access_token|secret|client_secret)\s*[:=]\s*(?!\[SECRET\]|\[REDACTED\])[^\s&,;]+', _mask_secret, text, flags=re.IGNORECASE)

        # 3. Credit Cards (multi-brand + Luhn validation)
        def _mask_card(match):
            raw = match.group(0)
            digits = re.sub(r'\D', '', raw)
            if 13 <= len(digits) <= 19 and _is_card_candidate(digits) and luhn_checksum(digits):
                summary["card"] += 1
                return f"**** **** **** {digits[-4:]}"
            return raw

        text = re.sub(r'\b(?:\d[ -]*?){13,19}\b', _mask_card, text)

        # 4. IBAN
        def _mask_iban(match):
            iban_str = match.group(0).replace(" ", "").upper()
            country = iban_str[:2]
            expected_len = IBAN_COUNTRY_LENGTHS.get(country)
            if expected_len and len(iban_str) == expected_len:
                summary["iban"] += 1
                return "[IBAN]"
            elif not expected_len and 15 <= len(iban_str) <= 34:
                summary["iban"] += 1
                return "[IBAN]"
            return match.group(0)

        text = re.sub(r'\b[A-Z]{2}\d{2}[A-Z0-9\s]{11,32}\b', _mask_iban, text)

        # 5. SSN
        def _mask_ssn(match):
            summary["ssn"] += 1
            return "[SSN]"

        text = re.sub(r'\b\d{3}-\d{2}-\d{4}\b', _mask_ssn, text)

        # 6. PAN (Indian Permanent Account Number: 5 letters, 4 digits, 1 letter)
        def _mask_pan(match):
            summary["pan"] += 1
            return "[PAN]"

        text = re.sub(r'\b[A-Z]{5}[0-9]{4}[A-Z]\b', _mask_pan, text)

        # 7. Aadhaar (12-digit Indian ID anchored by keyword: aadhaar, aadhar, uid, uidai within ~30 chars)
        def _mask_aadhaar(match):
            start_pos = max(0, match.start() - 30)
            end_pos = min(len(text), match.end() + 30)
            context = text[start_pos:end_pos]
            if re.search(r'(?i)\b(?:aadhaar|aadhar|uid|uidai)\b', context):
                raw = match.group(0)
                digits = re.sub(r'\D', '', raw)
                if len(digits) == 12 and digits[0] in "23456789":
                    summary["aadhaar"] += 1
                    return "[AADHAAR]"
            return match.group(0)

        text = re.sub(r'(?<!\d)(?<!\d[\s-])[2-9]\d{3}[\s-]?\d{4}[\s-]?\d{4}(?![\s-]?\d)', _mask_aadhaar, text)

        # 8. Email (avoid matching URL userinfo e.g. http://user:pass@host)
        def _mask_email(match):
            summary["email"] += 1
            return "[EMAIL]"

        text = re.sub(r'(?<![:/])\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b', _mask_email, text)

        # 9. Phone Numbers (E.164 with +, US formatted with separators/parens, IN 10-digit)
        def _mask_phone(match):
            summary["phone"] += 1
            return "[PHONE]"

        phone_pattern = r'(?:\+\s*1[-.\s]*)?\(\d{3}\)[-.\s]?\d{3}[-.\s]?\d{4}\b|\b(?:\+?1[-.\s])\d{3}[-.\s]\d{3}[-.\s]\d{4}\b|\b\d{3}[-.]\d{3}[-.]\d{4}\b|(?:\+\s*91[-.\s]*|\b91[-.\s]*|\b)[6-9]\d{4}[-.\s]?\d{5}\b|\b\+[1-9]\d{7,14}\b'
        text = re.sub(phone_pattern, _mask_phone, text)

        # 10. IP Addresses
        def _mask_ip(match):
            summary["ip"] += 1
            return "[IP]"

        text = re.sub(r'\b(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\b', _mask_ip, text)

        # 11. Contextual Date of Birth (DOB)
        dob_keywords_pattern = r'(?i)\b(?:dob|date of birth|birth date|born|birthday)\s*(?:[:=,-]|\bis\b|\bwas\b|\bon\b)*\s*(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}[/-]\d{1,2}[/-]\d{1,2}|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2}(?:st|nd|rd|th)?,?\s+\d{4})'
        def _mask_dob(match):
            summary["dob"] += 1
            full_match = match.group(0)
            date_part = match.group(1)
            return full_match.replace(date_part, "[DOB]")

        text = re.sub(dob_keywords_pattern, _mask_dob, text)

        # 12. Postal Addresses
        address_pattern = r'\b\d{1,5}\s+[A-Za-z0-9\s.,]+(?:Street|St|Avenue|Ave|Road|Rd|Boulevard|Blvd|Lane|Ln|Drive|Dr|Way|Court|Ct|Circle|Cir|Highway|Hwy|Parkway|Pkwy|Plaza|Plz|Square|Sq|Terrace|Ter|Suite|Ste|Apt|Apartment)\b(?:\s*,?\s*[A-Za-z\s]+)?(?:\s*,?\s*[A-Z]{2})?(?:\s*,?\s*\d{5}(?:-\d{4})?)?'
        def _mask_address(match):
            val = match.group(0)
            if val.lower().strip() in DOMAIN_ALLOWLIST:
                return val
            summary["address"] += 1
            return "[ADDRESS]"

        text = re.sub(address_pattern, _mask_address, text, flags=re.IGNORECASE)

        # 13. Person Names (NER-lite with domain allowlist)
        honorific_pattern = r'\b(?:Mr\.|Mrs\.|Ms\.|Dr\.|Prof\.)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\b'
        def _mask_honorific_name(match):
            name_part = match.group(1)
            if name_part.lower() not in DOMAIN_ALLOWLIST and not re.match(r'^[A-Z]+-\d+$', name_part):
                summary["name"] += 1
                return "[NAME]"
            return match.group(0)

        text = re.sub(honorific_pattern, _mask_honorific_name, text)

        label_name_pattern = r'(?i)\b(name|customer|assignee|reported by)\s*:\s*([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\b'
        def _mask_label_name(match):
            label = match.group(1)
            name_part = match.group(2)
            if name_part.lower() not in DOMAIN_ALLOWLIST and not re.match(r'^[A-Z]+-\d+$', name_part):
                summary["name"] += 1
                return f"{label}: [NAME]"
            return match.group(0)

        text = re.sub(label_name_pattern, _mask_label_name, text)

        if _SPACY_NLP:
            try:
                doc = _SPACY_NLP(text)
                for ent in reversed(doc.ents):
                    if ent.label_ == "PERSON":
                        ent_text = ent.text.strip()
                        if (
                            ent_text.lower() not in DOMAIN_ALLOWLIST
                            and not re.match(r'^[A-Z]+-\d+$', ent_text)
                            and not ent_text.startswith("[")
                        ):
                            summary["name"] += 1
                            text = text[:ent.start_char] + "[NAME]" + text[ent.end_char:]
            except Exception:
                pass

        active_summary = {k: v for k, v in summary.items() if v > 0}
        return text, active_summary


PII_PATTERNS = [
    (r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', '[EMAIL]'),
    (r'\b(?:\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b', '[PHONE]'),
    (r'\b\d{3}-\d{2}-\d{4}\b', '[SSN]'),
    (r'\b[A-Z]{5}[0-9]{4}[A-Z]\b', '[PAN]'),
    (r'\b(?:password|passwd|pwd)\s*[:=]\s*\S+', '[PASSWORD]'),
    (r'\b(?:token|api_key|secret)\s*[:=]\s*\S+', '[SECRET]'),
    (r'\bhttps?://[^\s]+', '[URL]'),
    (r'\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b', '[IP]'),
]


def mask_pii_with_summary(text: str, url_mode: Optional[str] = None) -> Tuple[str, Dict[str, int]]:
    """Mask PII from text and return masked text along with audit summary."""
    masker = PIIMasker(url_mode=url_mode)
    return masker.mask_with_summary(text)


def mask_pii(text: str, url_mode: Optional[str] = None) -> str:
    """Mask PII from text before sending to AI (primary public entrypoint)."""
    masked_text, _ = mask_pii_with_summary(text, url_mode=url_mode)
    return masked_text