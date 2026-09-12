import pytest
from src.utils.pii_masker import mask_pii, mask_pii_with_summary, PIIMasker, luhn_checksum


@pytest.mark.parametrize(
    "brand,card_number,expected_last4",
    [
        ("Visa", "4111 1111 1111 1111", "1111"),
        ("Mastercard-51", "5105 1051 0510 5100", "5100"),
        ("Mastercard-2221", "2221 0011 1111 1115", "1115"),
        ("Amex", "3782 822463 10005", "0005"),
        ("Discover", "6011 1111 1111 1117", "1117"),
        ("JCB", "3528 0000 0000 0007", "0007"),
        ("Diners", "3056 930902 5904", "5904"),
        ("Maestro", "6761 8211 1111 1113", "1113"),
    ],
)
def test_credit_card_brands_mask_correctly(brand, card_number, expected_last4):
    assert luhn_checksum(card_number) is True
    text = f"Payment using {brand} card: {card_number} on checkout"
    masked = mask_pii(text)
    assert card_number not in masked
    assert f"**** **** **** {expected_last4}" in masked


def test_luhn_invalid_order_number_not_masked():
    # 16-digit number that fails Luhn checksum (order / invoice ID)
    invalid_number = "1234 5678 9012 3456"
    assert luhn_checksum(invalid_number) is False

    text = f"Order confirmation number: {invalid_number}"
    masked = mask_pii(text)
    assert invalid_number in masked
    assert "**** **** ****" not in masked


def test_structured_pii_detectors():
    # Email
    assert mask_pii("Contact user at alice.smith@example.co.uk") == "Contact user at [EMAIL]"

    # Phone numbers
    assert mask_pii("Call customer at +1 (555) 234-5678") == "Call customer at [PHONE]"
    assert mask_pii("Call support on +91 9876543210") == "Call support on [PHONE]"

    # SSN
    assert mask_pii("SSN is 123-45-6789 for identification") == "SSN is [SSN] for identification"

    # PAN
    assert mask_pii("Indian PAN card ABCDE1234F is required") == "Indian PAN card [PAN] is required"

    # Aadhaar (anchored by keyword: aadhaar, aadhar, uid, uidai)
    assert mask_pii("Aadhaar number 2345 6789 0123 provided") == "Aadhaar number [AADHAAR] provided"
    assert mask_pii("Verified via UID: 2345-6789-0123 successfully") == "Verified via UID: [AADHAAR] successfully"
    # Negative test: 12-digit order reference without anchor must NOT mask
    assert mask_pii("Order reference 234567890123 for invoice") == "Order reference 234567890123 for invoice"
    assert mask_pii("Build ID 2345 6789 0123 completed") == "Build ID 2345 6789 0123 completed"

    # IBAN
    assert mask_pii("Transfer to GB29 NWBK 6016 1331 9268 19") == "Transfer to [IBAN]"

    # Contextual DOB
    assert mask_pii("User DOB: 15/08/1990 in profile") == "User DOB: [DOB] in profile"
    assert mask_pii("Employee date of birth is 1985-12-01") == "Employee date of birth is [DOB]"

    # Postal address
    assert mask_pii("Ship item to 742 Evergreen Terrace, Springfield, OR 97477") == "Ship item to [ADDRESS]"


def test_ner_lite_person_names_and_domain_allowlist():
    # Honorific-triggered name should be masked
    assert mask_pii("Test verified by Mr. John Smith yesterday") == "Test verified by [NAME] yesterday"
    assert mask_pii("Reported by Dr. Jane Doe") == "Reported by [NAME]"

    # Label-triggered name
    assert mask_pii("assignee: Robert Johnson") == "assignee: [NAME]"

    # Domain allowlist and Jira ticket keys must NOT be masked
    text = "Login Page tested for PROJ-123 on Zephyr Scale with Playwright"
    masked = mask_pii(text)
    assert "Login Page" in masked
    assert "PROJ-123" in masked
    assert "Zephyr Scale" in masked
    assert "Playwright" in masked
    assert "[NAME]" not in masked


def test_url_masking_modes():
    url = "https://admin:secret123@api.example.com/v1/checkout?token=xyz987&session=abc123&page=2&lang=en"

    # Smart mode (default): keeps scheme, host, path; redacts userinfo and sensitive query values
    smart_masked = mask_pii(url, url_mode="smart")
    assert "https://" in smart_masked
    assert "api.example.com/v1/checkout" in smart_masked
    assert "page=2" in smart_masked
    assert "lang=en" in smart_masked
    assert "token=%5BREDACTED%5D" in smart_masked or "token=[REDACTED]" in smart_masked
    assert "session=%5BREDACTED%5D" in smart_masked or "session=[REDACTED]" in smart_masked
    assert "xyz987" not in smart_masked
    assert "secret123" not in smart_masked

    # Strict mode: replaces entire URL with [URL]
    strict_masked = mask_pii(url, url_mode="strict")
    assert strict_masked == "[URL]"

    # Off mode: leaves URL intact
    off_masked = mask_pii(url, url_mode="off")
    assert off_masked == url


def test_masking_idempotence():
    text = (
        "Customer Mr. John Smith with email john.smith@test.com and phone +1 555-123-4567 "
        "used card 4111 1111 1111 1111 at address 123 Main Street on https://app.example.com/pay?token=secret1"
    )
    first_pass = mask_pii(text)
    second_pass = mask_pii(first_pass)

    assert first_pass == second_pass


def test_mask_pii_with_summary():
    text = "Email: test@example.com, SSN: 123-45-6789, Card: 4111 1111 1111 1111"
    masked, summary = mask_pii_with_summary(text)

    assert summary.get("email") == 1
    assert summary.get("ssn") == 1
    assert summary.get("card") == 1
    assert "test@example.com" not in masked
