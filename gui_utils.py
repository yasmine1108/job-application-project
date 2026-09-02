"""
Helper functions for the Streamlit GUI.

Nothing here duplicates pipeline/matching/extraction logic -- it only
adapts existing pydantic models to/from pandas DataFrames (for
st.data_editor) and provides thin, GUI-specific wrappers around the
project's own building blocks (Matcher._load_existing,
load_application_logs, FallbackLLM, ...).

IMPORTANT -- import paths you may need to fix:
The uploaded files didn't reveal the exact module paths for CVParser,
CVExtractor and JobOfferExtractor (only their *content*, via flattened
filenames). The imports below are best-guesses based on how every other
file in the project imports things (`src.<package>.<module>`). If your
actual layout differs, just fix the four import lines marked "ADJUST"
below -- nothing else in this file depends on the exact path.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from pydantic import ValidationError

# --- project imports (these paths matched 1:1 across every uploaded file) ---
from src.models import (
    CandidateProfile,
    PersonalInformation,
    Education,
    Experience,
    Project,
    Skill,
    Certification,
    SpokenLanguage,
    ParsedDocument,
)
from src.models_job import DegreeLevel, SkillCategory
from src.matchers.matcher import Matcher, CandidatePreferences, MatchResult, RejectedMatch
from src.application_logging import load_application_logs, ApplicationLog
from src.candidate_identity import ensure_candidate_id
from src.llm.fallback import FallbackLLM
from src.llm.gemini_provider import GeminiProvider
from src.llm.groq_provider import GroqProvider
from config.settings import Settings

from src.ai_modules.cv_parser import CVParser
from src.ai_modules.cv_extractor import CVExtractor
from src.ai_modules.job_offer_extractor import JobOfferExtractor
from src.scrapers.job_board_scraper import register_scraper
from src.scrapers.tanitjobs import TanitJobsScraper
from src.scrapers.linkedin import LinkedInScraper


# ---------------------------------------------------------------------------
# Directories / paths (mirrors what the existing modules already assume)
# ---------------------------------------------------------------------------

DATA_DIR = Path("data")
CV_DIR = DATA_DIR / "cv"
OUTPUTS_DIR = DATA_DIR / "outputs"
CACHE_DIR = DATA_DIR / "cache"
PROFILES_DIR = DATA_DIR / "profiles"  # extracted CandidateProfile jsons -- kept OUT of data/outputs
                                        # on purpose, so it doesn't mix with matches/job_offers/applications.

CV_MANIFEST_PATH = CV_DIR / "manifest.json"  # tracks {stored_filename, original_filename, uploaded_at}

MATCHES_OUTPUT_PATH = OUTPUTS_DIR / "matches.json"
JOB_OFFERS_OUTPUT_PATH = OUTPUTS_DIR / "structured_jobs.json"
# NOTE: each scraper currently logs applications to its own file
# (see tanitjobs.py's self.applications_output_path /
# linkedin.py's equivalent) rather than to the single path pipeline.py
# threads through as `applications_log_path`. The GUI reads from all of
# them so the "Applications" tab is complete regardless of that mismatch.
APPLICATION_LOG_PATHS = [
    OUTPUTS_DIR / "tanitjobs_applications.json",
    OUTPUTS_DIR / "linkedin_applications.json",
]
DEFAULT_APPLICATIONS_LOG_PATH = APPLICATION_LOG_PATHS[0]

BOARD_DOMAINS = {
    "TanitJobs": "tanitjobs.com",
    "LinkedIn": "linkedin.com",
}


def format_validation_errors(exc: ValidationError) -> list[str]:
    """Turns a pydantic ValidationError into short, field-labelled strings
    the GUI can show as st.error() instead of letting the exception
    propagate into an ugly traceback."""
    messages = []
    for err in exc.errors():
        field = ".".join(str(p) for p in err["loc"]) or "(top level)"
        messages.append(f"**{field}**: {err['msg']}")
    return messages


def ensure_dirs() -> None:
    for d in (CV_DIR, OUTPUTS_DIR, CACHE_DIR, PROFILES_DIR):
        d.mkdir(parents=True, exist_ok=True)


def register_all_scrapers() -> None:
    """TanitJobsScraper/LinkedInScraper don't self-register via a
    module-level register_scraper(...) call, and pipeline.py only imports
    SCRAPER_REGISTRY/get_scraper_for_url (not the concrete classes) --
    so without this, SCRAPER_REGISTRY stays empty and
    get_scraper_for_url() raises for every job_url. Call this once at
    app startup, before any run_pipeline_for_candidate() call. Safe to
    call repeatedly (e.g. on every Streamlit rerun) since it's just a
    dict assignment, keyed by domain, so re-registering is a no-op."""
    register_scraper("tanitjobs.com", TanitJobsScraper)
    register_scraper("linkedin.com", LinkedInScraper)


# ---------------------------------------------------------------------------
# LLMs
# ---------------------------------------------------------------------------

def build_cv_llm():
    """Local Ollama model used only for CV extraction (CVExtractor.with_structured_output)."""
    from langchain_ollama import ChatOllama
    return ChatOllama(model=Settings.OLLAMA_MODEL, temperature=0)


def build_fallback_llm() -> FallbackLLM:
    """FallbackLLM used for matching / job-offer extraction / cover letters.
    Mirrors src/llm/providers.py's build_default_fallback_llm(), but with
    import paths consistent with the rest of this project (providers.py
    itself imports from an `agent_project.*` prefix that doesn't match
    anywhere else -- adjust here if that turns out to be the real prefix)."""
    if not Settings.GEMINI_API_KEY and not Settings.GROQ_API_KEY:
        raise RuntimeError(
            "No API key configured. Set GEMINI_API_KEY and/or GROQ_API_KEY "
            "in your .env before running the agent."
        )
    providers = []
    if Settings.GEMINI_API_KEY:
        providers += [
            GeminiProvider(Settings.GEMINI_API_KEY, "gemini-3.5-flash"),
            GeminiProvider(Settings.GEMINI_API_KEY, "gemini-3.5-flash-lite"),
        ]
    if Settings.GROQ_API_KEY:
        providers += [
            GroqProvider(Settings.GROQ_API_KEY, "openai/gpt-oss-120b"),
            GroqProvider(Settings.GROQ_API_KEY, "openai/gpt-oss-20b"),
        ]
    return FallbackLLM(providers)


# ---------------------------------------------------------------------------
# CV upload + extraction
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# CV manifest (persists which CVs have been uploaded, across GUI restarts)
# ---------------------------------------------------------------------------

def _load_cv_manifest() -> list[dict]:
    if not CV_MANIFEST_PATH.exists():
        return []
    try:
        entries = json.loads(CV_MANIFEST_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    # defensive: drop entries whose underlying file has since been deleted
    return [e for e in entries if (CV_DIR / e["stored_filename"]).exists()]


def _save_cv_manifest(entries: list[dict]) -> None:
    CV_MANIFEST_PATH.write_text(json.dumps(entries, indent=2, ensure_ascii=False), encoding="utf-8")


def list_uploaded_cvs() -> list[dict]:
    """Most-recently-uploaded first -- so 'just use the latest one' is index 0."""
    entries = _load_cv_manifest()
    return sorted(entries, key=lambda e: e["uploaded_at"], reverse=True)


def cv_display_label(entry: dict) -> str:
    ts = entry["uploaded_at"][:16].replace("T", " ")
    return f'{entry["original_filename"]}  ({ts})'


def save_uploaded_cv(uploaded_file) -> str:
    """Saves the Streamlit UploadedFile under data/cv/ with a unique
    filename (so two different CVs -- or two re-uploads of a file with the
    same name -- never collide), records it in the manifest, and returns
    the stored filename (what CVParser/profile lookups use going forward)."""
    ensure_dirs()
    original_name = os.path.basename(uploaded_file.name)
    stored_filename = f"{uuid.uuid4().hex[:8]}_{original_name}"
    dest = CV_DIR / stored_filename
    with open(dest, "wb") as f:
        f.write(uploaded_file.getbuffer())

    manifest = _load_cv_manifest()
    manifest.append({
        "stored_filename": stored_filename,
        "original_filename": original_name,
        "uploaded_at": datetime.now(timezone.utc).isoformat(),
    })
    _save_cv_manifest(manifest)
    return stored_filename


def extract_candidate_profile(cv_filename: str, llm) -> CandidateProfile:
    """Note: CVExtractor.extract() itself also writes its own cache copy to
    data/outputs/{stem}_profile.json internally (that's baked into
    cv_extractor.py, not something this GUI controls). save_profile()
    below writes the GUI's canonical, user-edited copy to PROFILES_DIR --
    that's the one this app reads back on reload."""
    parser = CVParser(cv_filename)
    document: ParsedDocument = parser.extract_text()
    extractor = CVExtractor(llm=llm, debug=False)
    return extractor.extract(document)


def profile_cache_path(cv_filename: str) -> Path:
    stem = Path(cv_filename).stem
    return PROFILES_DIR / f"{stem}_profile.json"


def save_profile(candidate: CandidateProfile, cv_filename: str) -> CandidateProfile:
    """Persists edits the same way CVExtractor.extract() does, so a later
    pipeline run (or a page refresh) sees the corrected profile."""
    ensure_dirs()
    cache_path = profile_cache_path(cv_filename)
    candidate = ensure_candidate_id(candidate, cache_path)
    with open(cache_path, "w", encoding="utf-8") as f:
        f.write(candidate.model_dump_json(indent=2))
    return candidate


def load_cached_profile(cv_filename: str) -> CandidateProfile | None:
    cache_path = profile_cache_path(cv_filename)
    if not cache_path.exists():
        return None
    return CandidateProfile.model_validate_json(cache_path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# DataFrame <-> pydantic list conversions (for st.data_editor)
# ---------------------------------------------------------------------------

def _clean_str(v) -> str | None:
    """Turns a data_editor cell into either a stripped string or None.
    Needed because empty cells (esp. on newly added rows) come back as
    float('nan'), not None/'' -- and `nan or None` is a no-op since
    float('nan') is truthy, which used to leak raw NaNs into pydantic
    `str | None` fields and blow up with 'Input should be a valid string'."""
    if v is None:
        return None
    if isinstance(v, float) and pd.isna(v):
        return None
    v = str(v).strip()
    return v or None


def _join(items: list[str] | None) -> str:
    return " | ".join(i for i in (items or []) if i)


def _split(text) -> list[str]:
    text = _clean_str(text)
    if not text:
        return []
    return [p.strip() for p in text.split("|") if p.strip()]


def education_to_df(items: list[Education]) -> pd.DataFrame:
    rows = [{
        "degree": e.degree, "degree_level": e.degree_level.value if e.degree_level else None,
        "years_of_study": e.years_of_study, "institution": e.institution,
        "field_of_study": e.field_of_study, "start_date": e.start_date,
        "end_date": e.end_date, "description": e.description,
    } for e in items]
    return pd.DataFrame(rows, columns=[
        "degree", "degree_level", "years_of_study", "institution",
        "field_of_study", "start_date", "end_date", "description",
    ])


def df_to_education(df: pd.DataFrame) -> list[Education]:
    out = []
    for _, r in df.iterrows():
        if not any(pd.notna(v) and str(v).strip() for v in r):
            continue
        out.append(Education(
            degree=_clean_str(r.get("degree")),
            degree_level=DegreeLevel(r["degree_level"]) if _clean_str(r.get("degree_level")) else None,
            years_of_study=int(r["years_of_study"]) if pd.notna(r.get("years_of_study")) else None,
            institution=_clean_str(r.get("institution")),
            field_of_study=_clean_str(r.get("field_of_study")),
            start_date=_clean_str(r.get("start_date")),
            end_date=_clean_str(r.get("end_date")),
            description=_clean_str(r.get("description")),
        ))
    return out


def experience_to_df(items: list[Experience]) -> pd.DataFrame:
    rows = [{
        "job_title": e.job_title, "company": e.company, "domain": e.domain,
        "location": e.location, "employment_type": e.employment_type,
        "start_date": e.start_date, "end_date": e.end_date,
        "duration_months": e.duration_months, "description": e.description,
        "responsibilities": _join(e.responsibilities), "technologies": _join(e.technologies),
    } for e in items]
    return pd.DataFrame(rows, columns=[
        "job_title", "company", "domain", "location", "employment_type",
        "start_date", "end_date", "duration_months", "description",
        "responsibilities", "technologies",
    ])


def df_to_experience(df: pd.DataFrame) -> list[Experience]:
    out = []
    for _, r in df.iterrows():
        if not any(pd.notna(v) and str(v).strip() for v in r):
            continue
        out.append(Experience(
            job_title=_clean_str(r.get("job_title")),
            company=_clean_str(r.get("company")),
            domain=_clean_str(r.get("domain")),
            location=_clean_str(r.get("location")),
            employment_type=_clean_str(r.get("employment_type")),
            start_date=_clean_str(r.get("start_date")),
            end_date=_clean_str(r.get("end_date")),
            duration_months=int(r["duration_months"]) if pd.notna(r.get("duration_months")) else None,
            description=_clean_str(r.get("description")),
            responsibilities=_split(r.get("responsibilities")),
            technologies=_split(r.get("technologies")),
        ))
    return out


def projects_to_df(items: list[Project]) -> pd.DataFrame:
    rows = [{
        "title": p.title, "summary": p.summary, "highlights": _join(p.highlights),
        "technologies": _join(p.technologies), "github": p.github,
    } for p in items]
    return pd.DataFrame(rows, columns=["title", "summary", "highlights", "technologies", "github"])


def df_to_projects(df: pd.DataFrame) -> list[Project]:
    out = []
    for _, r in df.iterrows():
        if not any(pd.notna(v) and str(v).strip() for v in r):
            continue
        out.append(Project(
            title=_clean_str(r.get("title")),
            summary=_clean_str(r.get("summary")),
            highlights=_split(r.get("highlights")),
            technologies=_split(r.get("technologies")),
            github=_clean_str(r.get("github")),
        ))
    return out


def skills_to_df(items: list[Skill]) -> pd.DataFrame:
    rows = [{
        "name": s.name, "category": s.category.value if s.category else None,
        "evidence": _join(s.evidence),
    } for s in items]
    return pd.DataFrame(rows, columns=["name", "category", "evidence"])


def df_to_skills(df: pd.DataFrame) -> list[Skill]:
    out = []
    for _, r in df.iterrows():
        name = _clean_str(r.get("name"))
        if not name:
            continue
        out.append(Skill(
            name=name,
            category=SkillCategory(r["category"]) if _clean_str(r.get("category")) else None,
            evidence=_split(r.get("evidence")) or None,
        ))
    return out


def certifications_to_df(items: list[Certification]) -> pd.DataFrame:
    rows = [{"name": c.name, "issuer": c.issuer, "date": c.date} for c in items]
    return pd.DataFrame(rows, columns=["name", "issuer", "date"])


def df_to_certifications(df: pd.DataFrame) -> list[Certification]:
    out = []
    for _, r in df.iterrows():
        name = _clean_str(r.get("name"))
        if not name:
            continue
        out.append(Certification(name=name, issuer=_clean_str(r.get("issuer")), date=_clean_str(r.get("date"))))
    return out


def spoken_languages_to_df(items: list[SpokenLanguage]) -> pd.DataFrame:
    rows = [{"name": s.name, "proficiency": s.proficiency} for s in items]
    return pd.DataFrame(rows, columns=["name", "proficiency"])


def df_to_spoken_languages(df: pd.DataFrame) -> list[SpokenLanguage]:
    out = []
    for _, r in df.iterrows():
        name = _clean_str(r.get("name"))
        if not name:
            continue
        out.append(SpokenLanguage(name=name, proficiency=_clean_str(r.get("proficiency"))))
    return out


# ---------------------------------------------------------------------------
# Matches / applications (read-only views over existing outputs)
# ---------------------------------------------------------------------------

def load_matches(candidate_id: str) -> tuple[list[MatchResult], list[RejectedMatch]]:
    """Reuses Matcher's own (de)serialization instead of re-implementing it.
    No llm needed for a read-only load."""
    ensure_dirs()
    matcher = Matcher(llm=None, output_path=MATCHES_OUTPUT_PATH)
    return matcher._load_existing(candidate_id)


def matches_to_df(results: list[MatchResult]) -> pd.DataFrame:
    rows = [{
        "job_url": r.job_url,
        "overall_score": round(r.overall_score, 3),
        "apply_priority": round(r.apply_priority, 3),
        "skills_fit": round(r.judgment.skills_fit.score, 2),
        "experience_fit": round(r.judgment.experience_fit.score, 2),
        "education_fit": round(r.judgment.education_fit.score, 2),
        "summary": r.judgment.summary,
    } for r in results]
    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values("apply_priority", ascending=False)
    return df


def rejected_to_df(rejected: list[RejectedMatch]) -> pd.DataFrame:
    return pd.DataFrame([{"job_url": r.job_url, "reason": r.rejection_reason} for r in rejected])


def load_all_applications(candidate_id: str) -> pd.DataFrame:
    ensure_dirs()
    logs: list[ApplicationLog] = []
    for path in APPLICATION_LOG_PATHS:
        logs.extend(load_application_logs(path, candidate_id))
    logs.sort(key=lambda l: l.applied_at, reverse=True)
    rows = [{
        "job_url": l.job_url, "dry_run": l.dry_run, "submitted": l.submitted,
        "cover_letter_source": l.cover_letter_source, "applied_at": l.applied_at,
        "name": l.payload.get("name"), "email": l.payload.get("email"),
    } for l in logs]
    return pd.DataFrame(rows)