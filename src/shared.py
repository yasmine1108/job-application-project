import re
from rapidfuzz import process, fuzz

DEGREE_LEVEL_GUIDANCE = (
    "Normalize by total years of post-secondary study, NOT by literal degree "
    "name — titles differ across education systems. Examples: French Bac = "
    "HIGH_SCHOOL. Classe Préparatoire (CPGE) alone = SHORT_CYCLE (2 yrs, no "
    "standalone degree). BTS/DUT = ASSOCIATE (~2 yrs, degree awarded). Licence "
    "= BACHELOR (~3 yrs). Diplôme d'Ingénieur, Master, MBA = MASTER (~5 yrs "
    "total, master-equivalent). Doctorat/PhD = DOCTORATE (~8 yrs)."
)

SKILL_ALIASES: dict[str, set[str]] = {
    "javascript": {"js", "javascript", "java script"},
    "typescript": {"ts", "typescript"},
    "python": {"python", "python3", "python 3", "py"},
    "postgresql": {"postgres", "postgresql", "psql"},
    "node.js": {"node", "nodejs", "node.js"},
    "react": {"react", "react.js", "reactjs"},
    "amazon web services": {"aws", "amazon web services"},
    "kubernetes": {"k8s", "kubernetes"},
    "c#": {"c#", "csharp", "c sharp"},
    "c++": {"c++", "cpp", "c plus plus"},
    "html": {"html", "html5"},
    "css": {"css", "css3"},
}

_ALIAS_TO_CANONICAL: dict[str, str] = {
    alias: canonical
    for canonical, aliases in SKILL_ALIASES.items()
    for alias in aliases
}

def normalize_skill_name(raw_name: str) -> str:
    """Map a raw skill string to its canonical form. Falls back to a cleaned
    version of the original if no alias is known."""
    cleaned = re.sub(r"\s+", " ", raw_name.strip().lower())

    if cleaned in _ALIAS_TO_CANONICAL:
        return _ALIAS_TO_CANONICAL[cleaned]

    match = process.extractOne(cleaned, SKILL_ALIASES.keys(), scorer=fuzz.ratio)
    if match and match[1] >= 92:
        return match[0]

    return raw_name.strip()

