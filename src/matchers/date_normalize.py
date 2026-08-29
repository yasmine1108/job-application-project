# linkedin.py or a new src/matchers/date_normalize.py
from babel.dates import get_month_names
import re
import unicodedata

def _strip_accents(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))

def _build_month_lookup() -> dict[str, str]:
    lookup = {}
    for width in ("wide", "abbreviated"):
        fr_names = get_month_names(width, locale="fr")
        en_names = get_month_names(width, locale="en")
        for num, fr_name in fr_names.items():
            key = _strip_accents(fr_name.strip().lower()).rstrip(".")
            lookup[key] = en_names[num]
        for num, en_name in en_names.items():
            lookup[_strip_accents(en_name.strip().lower()).rstrip(".")] = en_name  # CVs already in English
    return lookup

_MONTH_LOOKUP = _build_month_lookup()

def parse_month_year(raw: str | None) -> tuple[str | None, str | None]:
    """From a free-text date like 'Sept. 2024' or 'Present' -> ('September', '2024').
    Returns (None, None) if unparseable (caller should skip the field, not guess)."""
    if not raw or not raw.strip():
        return None, None

    year_match = re.search(r"\b(19|20)\d{2}\b", raw)
    year = year_match.group(0) if year_match else None

    for token in re.findall(r"[A-Za-zÀ-ÿ]+", raw):
        key = _strip_accents(token.lower()).rstrip(".")
        if key in _MONTH_LOOKUP:
            return _MONTH_LOOKUP[key], year

    return None, year