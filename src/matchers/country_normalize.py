"""
Normalizes country names to ISO 3166-1 alpha-2 codes so comparisons like
"Tunisie" vs "Tunisia" or "UK" vs "United Kingdom" don't falsely register
as different countries.

Unlike skill names, the set of countries is small, closed, and already has
an authoritative standard (ISO 3166) — so this is solved with a lookup
table built from pycountry + babel's locale data, not an LLM/embedding
fallback. No hand-maintained alias dict to keep growing.
"""

import pycountry
from babel import Locale

# Informal short forms that aren't official ISO names/official_names and
# so wouldn't otherwise appear in the lookup. Keep this list small — it's
# only for well-known colloquialisms, not a general alias mechanism.
_MANUAL_ALIASES = {
    "uk": "GB",
    "u.k.": "GB",
    "usa": "US",
    "u.s.a.": "US",
    "us": "US",
    "uae": "AE",
    "ivory coast": "CI",
}


def _build_country_lookup() -> dict[str, str]:
    lookup: dict[str, str] = {}

    for country in pycountry.countries:
        for name in (country.name, getattr(country, "official_name", None)):
            if name:
                lookup[name.strip().lower()] = country.alpha_2
        lookup[country.alpha_2.lower()] = country.alpha_2
        lookup[country.alpha_3.lower()] = country.alpha_2

    # French display names (covers "Tunisie", "Royaume-Uni", "États-Unis", etc.)
    # Babel ships locale data for many languages — add more Locale(...) calls
    # here if job postings show up in other languages (e.g. Arabic).
    for alpha_2, fr_name in Locale("fr").territories.items():
        if len(alpha_2) == 2 and fr_name:
            lookup[fr_name.strip().lower()] = alpha_2

    lookup.update(_MANUAL_ALIASES)
    return lookup


_COUNTRY_LOOKUP = _build_country_lookup()


def normalize_country(raw: str | None) -> str | None:
    """Returns an ISO 3166-1 alpha-2 code (e.g. 'TN', 'GB'), or None if the
    input is empty or genuinely unrecognized."""
    if not raw or not raw.strip():
        return None

    key = raw.strip().lower()
    if key in _COUNTRY_LOOKUP:
        return _COUNTRY_LOOKUP[key]

    # Fallback: pycountry's fuzzy search handles accents, partial names,
    # and minor typos that a plain dict lookup would miss.
    try:
        matches = pycountry.countries.search_fuzzy(raw.strip())
        if matches:
            return matches[0].alpha_2
    except LookupError:
        pass

    return None
