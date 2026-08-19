"""
Job-candidate matcher.

Design:
- Hard filters (deterministic, free) reject jobs that can't be matched at all
  (closed, already applied, missing required spoken language).
- Remaining jobs are scored by an LLM in batches: candidate profile sent once,
  N jobs per call (structured data + raw description for nuance/soft skills).
- The LLM scores each dimension independently (skills_fit, experience_fit,
  education_fit) with a short explanation. It does NOT compute the overall
  score itself — that's done deterministically here via compute_overall_score,
  so the weighting is reliable and easy to retune without re-calling the LLM.
- Results are saved after every batch so a rate-limit/crash mid-run doesn't
  lose progress, and a re-run skips jobs already matched for this candidate.
"""

import json
from pathlib import Path

from pydantic import BaseModel, Field

from src.matchers.country_normalize import normalize_country
from src.llm.fallback import FallbackLLM
from src.models import MatchingProfile, SpokenLanguage
from src.models_job import EmploymentType, JobOffer, JobStatus, RawJob, WorkArrangement
import math

# approximate centroid coordinates (lat, lon) for each Tunisian governorate
TUNISIA_GOVERNORATE_COORDS: dict[str, tuple[float, float]] = {
    "tunis": (36.8065, 10.1815),
    "ariana": (36.8625, 10.1956),
    "ben arous": (36.7533, 10.2189),
    "manouba": (36.8081, 10.0972),
    "nabeul": (36.4561, 10.7376),
    "zaghouan": (36.4028, 10.1425),
    "bizerte": (37.2744, 9.8739),
    "beja": (36.7256, 9.1817),
    "jendouba": (36.5011, 8.7803),
    "kef": (36.1742, 8.7049),
    "siliana": (36.0847, 9.3708),
    "kairouan": (35.6781, 10.0963),
    "kasserine": (35.1676, 8.8365),
    "sidi bouzid": (35.0381, 9.4858),
    "sousse": (35.8256, 10.6084),
    "monastir": (35.7780, 10.8262),
    "mahdia": (35.5047, 11.0622),
    "sfax": (34.7406, 10.7603),
    "gafsa": (34.4250, 8.7842),
    "tozeur": (33.9197, 8.1335),
    "kebili": (33.7044, 8.9690),
    "gabes": (33.8815, 10.0982),
    "medenine": (33.3549, 10.5055),
    "tataouine": (32.9297, 10.4518),
}


def haversine_km(coord1: tuple[float, float], coord2: tuple[float, float]) -> float:
    lat1, lon1 = coord1
    lat2, lon2 = coord2
    R = 6371  # Earth radius in km
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def governorate_distance_km(gov_a: str, gov_b: str) -> float | None:
    a = TUNISIA_GOVERNORATE_COORDS.get(gov_a.strip().lower())
    b = TUNISIA_GOVERNORATE_COORDS.get(gov_b.strip().lower())
    if a is None or b is None:
        return None
    return haversine_km(a, b)

def parse_job_location(location: str | None) -> tuple[str | None, str | None]:
    """Returns (governorate, country), best-effort from a 'City, Governorate, Country' string."""
    if not location:
        return None, None
    parts = [p.strip() for p in location.split(",")]
    if len(parts) >= 2:
        return parts[-2], parts[-1]
    return None, parts[-1] if parts else None

PROFICIENCY_RANK = {
    "basic": 1,
    "conversational": 2,
    "professional": 3,
    "fluent": 4,
    "native": 5,
}
ADVANCED_PROFICIENCY_THRESHOLD = PROFICIENCY_RANK["fluent"]  # "fluent" or "native" required = advanced


def proficiency_rank(level: str | None) -> int:
    if not level:
        return 0
    return PROFICIENCY_RANK.get(level.strip().lower(), 0)

class CandidatePreferences(BaseModel):
    preferred_employment_types: list[EmploymentType] = Field(default_factory=list)  # empty = no restriction
    preferred_work_arrangements: list[WorkArrangement] = Field(default_factory=list)
    willing_to_relocate: bool = False
    country: str
    governorate: str | None = None
    max_commute_distance_km: float | None = None  # None = no distance restriction


# ---------------------------------------------------------------------------
# Output models
# ---------------------------------------------------------------------------

class DimensionJudgment(BaseModel):
    score: float = Field(ge=0, le=1)
    explanation: str = Field(
        description="One concise sentence justifying this score, grounded in the provided profiles."
    )


class MatchJudgment(BaseModel):
    job_id: str = Field(
        description="The job_id value given for this job in the prompt. Echo it back exactly, unchanged."
    )
    skills_fit: DimensionJudgment
    experience_fit: DimensionJudgment
    education_fit: DimensionJudgment
    summary: str = Field(
        description="2-3 sentence human-readable overview of the fit, covering nuance not captured by the individual scores."
    )


class MatchJudgmentBatch(BaseModel):
    results: list[MatchJudgment]


class MatchResult(BaseModel):
    """What actually gets stored/ranked. Wraps MatchJudgment with the
    deterministically computed overall score and apply priority."""
    job_url: str
    candidate_id: str
    judgment: MatchJudgment
    overall_score: float = Field(ge=0, le=1)
    apply_priority: float = Field(ge=0, le=1)


class RejectedMatch(BaseModel):
    job_url: str
    candidate_id: str
    rejection_reason: str


# ---------------------------------------------------------------------------
# Weights — single source of truth for aggregation
# ---------------------------------------------------------------------------

MATCH_DIMENSION_WEIGHTS = {
    "skills_fit": 0.50,
    "experience_fit": 0.30,
    "education_fit": 0.20,
}


def compute_overall_score(judgment: MatchJudgment) -> float:
    return (
        MATCH_DIMENSION_WEIGHTS["skills_fit"] * judgment.skills_fit.score
        + MATCH_DIMENSION_WEIGHTS["experience_fit"] * judgment.experience_fit.score
        + MATCH_DIMENSION_WEIGHTS["education_fit"] * judgment.education_fit.score
    )


def compute_apply_priority(overall_score: float, easy_apply: bool) -> float:
    boost = 0.15 if easy_apply else 0.0
    return min(1.0, overall_score + boost)


# ---------------------------------------------------------------------------
# Hard filters — deterministic, run before any LLM call
# ---------------------------------------------------------------------------

COMMON_LANGUAGES = {"french", "français", "english", "anglais"}


def apply_hard_filters(
    job: JobOffer,
    candidate_langs: list[SpokenLanguage],
    preferences: CandidatePreferences,
) -> str | None:
    if job.job_status == JobStatus.CLOSED:
        return "Job is no longer accepting applications"

    # --- employment type preference ---
    if (
        preferences.preferred_employment_types
        and job.employment_type
        and job.employment_type not in preferences.preferred_employment_types
    ):
        return f"Employment type {job.employment_type.value} not in candidate's preferences"

    # --- work arrangement preference ---
    if (
        preferences.preferred_work_arrangements
        and job.work_arrangement
        and job.work_arrangement not in preferences.preferred_work_arrangements
    ):
        return f"Work arrangement {job.work_arrangement.value} not in candidate's preferences"

    # --- relocation check: on-site job abroad, candidate won't relocate ---
    job_governorate, job_country_raw = parse_job_location(job.location)

    job_country_code = normalize_country(job_country_raw)
    preference_country_code = normalize_country(preferences.country)

    if (
        job.work_arrangement == WorkArrangement.ON_SITE
        and job_country_code
        and preference_country_code
        and job_country_code != preference_country_code
        and not preferences.willing_to_relocate
    ):
        return f"On-site job in {job_country_raw}, candidate not willing to relocate"

    # --- optional distance filter: same country, different governorate ---
    if (
        preferences.max_commute_distance_km is not None
        and job.work_arrangement == WorkArrangement.ON_SITE
        and job_country_code and preference_country_code
        and job_country_code == preference_country_code
        and job_governorate
        and preferences.governorate
    ):
        distance = governorate_distance_km(job_governorate, preferences.governorate)
        if distance is not None and distance > preferences.max_commute_distance_km:
            return f"On-site job {distance:.0f}km away exceeds max commute of {preferences.max_commute_distance_km}km"

    # --- spoken language requirements ---
    candidate_lang_map = {l.name.strip().lower(): l.proficiency for l in candidate_langs}
    for req in job.required_languages:
        req_name = req.name.strip().lower()
        req_rank = proficiency_rank(req.min_proficiency)

        if req_name not in COMMON_LANGUAGES:
            # non fr/en language required — reject unless candidate explicitly has it
            if req_name not in candidate_lang_map:
                return f"Missing required language: {req.name}"
            continue

        # fr/en: only enforce if job explicitly demands an advanced level
        if req_rank >= ADVANCED_PROFICIENCY_THRESHOLD:
            candidate_level = candidate_lang_map.get(req_name)
            candidate_rank = proficiency_rank(candidate_level)
            if candidate_rank < req_rank:
                return f"Required {req.name} at '{req.min_proficiency}' level, candidate has '{candidate_level or 'unspecified'}'"

    return None


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------

class JobForMatching(BaseModel):
    job_url: str
    job_id: str
    structured: JobOffer
    raw_description: str


MATCH_SYSTEM_PROMPT = (
    "You are a job-matching evaluator. You will receive a candidate's "
    "structured profile once, followed by a list of job offers. Each job "
    "includes BOTH structured extracted data AND the raw job description text.\n\n"
    "Use the structured data as your primary source for hard facts (required "
    "skills list, years of experience, degree level). Use the RAW DESCRIPTION "
    "TEXT specifically to judge soft skills, team culture, and role nuance "
    "that a flattened skill list can lose — e.g. a bare word like "
    "'autonomie' in the structured list doesn't convey whether the role "
    "implies a fast-paced startup environment or a highly structured one; "
    "read the actual sentence it came from in the raw text for that context.\n\n"
    "Score each dimension 0.0-1.0 independently — do not average them "
    "yourself, a separate system computes the weighted total. For context, "
    "these are the relative weights that will be applied: skills_fit 50%, "
    "experience_fit 30%, education_fit 20%. Keep this in mind when writing "
    "your summary, but score each dimension on its own merits:\n"
    "- skills_fit: overlap between required job skills and candidate skills. "
    "Treat clearly synonymous tools/frameworks as partial (not zero) matches "
    "(e.g. a candidate skilled in one JS framework is a partial fit for a "
    "job requiring a different JS framework), but do not invent skills the "
    "candidate does not have evidence for.\n"
    "- experience_fit: candidate's total relevant experience vs required "
    "years/seniority stated in the job.\n"
    "- education_fit: candidate's highest education vs required degree "
    "level/field.\n\n"
    "Do not invent skills, experience, or education not evidenced in either "
    "the structured data or the raw text.\n\n"
    "Each job is labeled with a job_id (a short alphanumeric string). Return "
    "exactly one result per input job, with job_id set to the exact value "
    "given for that job — do not alter, re-derive, guess, or attempt to "
    "reproduce the job's URL or title as an identifier; job_id is the only "
    "identifier needed."
)


def build_match_prompt(candidate: MatchingProfile, jobs_for_matching: list[JobForMatching]) -> str:
    candidate_json = candidate.model_dump_json(indent=2)
    jobs_blocks = []
    for j in jobs_for_matching:
        jobs_blocks.append(
            f"job_id: {j.job_id}\n"
            f"STRUCTURED DATA:\n{j.structured.model_dump_json(indent=2)}\n\n"
            f"RAW JOB DESCRIPTION (use this for nuance, especially soft "
            f"skills/culture — the structured skill list may be incomplete "
            f"or flattened):\n{j.raw_description}"
        )
    jobs_text = "\n\n---\n\n".join(jobs_blocks)
    return f"CANDIDATE PROFILE:\n{candidate_json}\n\nJOB OFFERS:\n\n{jobs_text}"


# ---------------------------------------------------------------------------
# Matcher
# ---------------------------------------------------------------------------

class Matcher:
    def __init__(
        self,
        llm: FallbackLLM,
        output_path: str | Path,
        batch_size: int = 8,
    ):
        self.llm = llm
        self.output_path = Path(output_path)
        self.batch_size = batch_size

    def match_batch(
            self, candidate: MatchingProfile, jobs_for_matching: list[JobForMatching]
        ) -> dict[str, MatchJudgment]:
            prompt = build_match_prompt(candidate, jobs_for_matching)
            batch = self.llm.generate_structured(MATCH_SYSTEM_PROMPT, prompt, MatchJudgmentBatch)

            url_by_job_id = {j.job_id: j.job_url for j in jobs_for_matching}
            if len(url_by_job_id) != len(jobs_for_matching):
                print("WARNING: duplicate job_id values in this batch — job_id lookup may be unreliable, check upstream extraction")

            results_by_url: dict[str, MatchJudgment] = {}
            for r in batch.results:
                job_url = url_by_job_id.get(r.job_id)
                if job_url is None:
                    print(f"WARNING: LLM returned unknown job_id {r.job_id!r} (not in this batch), skipping")
                    continue
                results_by_url[job_url] = r
            return results_by_url
    def run(
        self,
        candidate_id: str,
        candidate: MatchingProfile,
        candidate_langs: list[str],
        jobs: list[JobOffer],
        raw_jobs_by_url: dict[str, RawJob],
        preferences: CandidatePreferences,
    ) -> list[MatchResult]:
        results, rejected = self._load_existing(candidate_id)
        already_done = {r.job_url for r in results} | {r.job_url for r in rejected}

        to_score: list[JobOffer] = []
        for job in jobs:
            if job.job_url in already_done:
                continue
            reason = apply_hard_filters(job, candidate_langs,preferences)
            if reason:
                rejected.append(RejectedMatch(job_url=job.job_url, candidate_id=candidate_id, rejection_reason=reason))
            else:
                to_score.append(job)

        self._save(candidate_id, results, rejected)  # persist filter pass immediately

        for i in range(0, len(to_score), self.batch_size):
            chunk = to_score[i : i + self.batch_size]
            jobs_for_matching = [
                JobForMatching(
                    job_url=j.job_url,
                    job_id=j.job_id or j.job_url,
                    structured=j,
                    raw_description=raw_jobs_by_url.get(j.job_url, RawJob()).description or "",
                )
                for j in chunk
            ]

            try:
                judged_by_url = self.match_batch(candidate, jobs_for_matching)
            except Exception as e:
                print(f"Batch {i}-{i + len(chunk)} failed ({e}), saving progress and stopping.")
                self._save(candidate_id, results, rejected)
                raise

            for job in chunk:
                judgment = judged_by_url.get(job.job_url)
                if judgment is None:
                    print(f"WARNING: no judgment returned for {job.job_url}, skipping")
                    continue
                overall = compute_overall_score(judgment)
                results.append(
                    MatchResult(
                        job_url=job.job_url,
                        candidate_id=candidate_id,
                        judgment=judgment,
                        overall_score=overall,
                        apply_priority=compute_apply_priority(overall, job.easy_apply),
                    )
                )

            self._save(candidate_id, results, rejected)

        return results

    # -- persistence -------------------------------------------------------

    def _load_existing(self, candidate_id: str) -> tuple[list[MatchResult], list[RejectedMatch]]:
        if not self.output_path.exists():
            return [], []
        try:
            with self.output_path.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError:
            return [], []

        all_results = [MatchResult.model_validate(r) for r in data.get("results", [])]
        all_rejected = [RejectedMatch.model_validate(r) for r in data.get("rejected", [])]

        return (
            [r for r in all_results if r.candidate_id == candidate_id],
            [r for r in all_rejected if r.candidate_id == candidate_id],
        )

    def _save(self, candidate_id: str, results: list[MatchResult], rejected: list[RejectedMatch]) -> None:
        self.output_path.parent.mkdir(parents=True, exist_ok=True)

        existing_results, existing_rejected = [], []
        if self.output_path.exists():
            try:
                with self.output_path.open("r", encoding="utf-8") as f:
                    data = json.load(f)
                existing_results = [MatchResult.model_validate(r) for r in data.get("results", [])]
                existing_rejected = [RejectedMatch.model_validate(r) for r in data.get("rejected", [])]
            except json.JSONDecodeError:
                pass

        # keep other candidates' data untouched, replace this candidate's data
        other_results = [r for r in existing_results if r.candidate_id != candidate_id]
        other_rejected = [r for r in existing_rejected if r.candidate_id != candidate_id]

        payload = {
            "results": [r.model_dump(mode="json") for r in other_results + results],
            "rejected": [r.model_dump(mode="json") for r in other_rejected + rejected],
        }

        with self.output_path.open("w", encoding="utf-8") as f:
            json.dump(payload, f, indent=4, ensure_ascii=False)