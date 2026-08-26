import pytest

from src.ai_modules.cv_extractor import extract_phone_country_code


@pytest.mark.parametrize(
    ("phone", "expected_country_code"),
    [
        ("+216 24 305 500", "TN"),
        ("00216 24 305 500", "TN"),
        ("+1 202-555-0123", "US"),
        ("24 305 500", None),
        (None, None),
        ("", None),
        ("not a phone number", None),
        ("+216 00 000 000", None),
    ],
)
def test_extract_phone_country_code(phone, expected_country_code):
    assert extract_phone_country_code(phone) == expected_country_code