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

from src.llm.fallback import FallbackLLM
from src.models import MatchingProfile
from src.models_job import ApplicationStatus, JobOffer, RawJob


# ---------------------------------------------------------------------------
# Output models
# ---------------------------------------------------------------------------

class DimensionJudgment(BaseModel):
    score: float = Field(ge=0, le=1)
    explanation: str = Field(
        description="One concise sentence justifying this score, grounded in the provided profiles."
    )


class MatchJudgment(BaseModel):
    job_url: str
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

def apply_hard_filters(job: JobOffer, candidate_langs: list[str]) -> str | None:
    """Returns a rejection reason, or None if the job should be scored."""
    if job.application_status == ApplicationStatus.CLOSED:
        return "Job is no longer accepting applications"

    if job.application_status != ApplicationStatus.NOT_APPLIED:
        return f"Already in status: {job.application_status.value}"

    # required_lang_names = {l.name.lower() for l in job.required_languages}
    # candidate_lang_names = {l.lower() for l in candidate_langs}
    # if required_lang_names and not required_lang_names & candidate_lang_names:
    #     return f"Missing required language(s): {sorted(required_lang_names)}"

    return None


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------

class JobForMatching(BaseModel):
    job_url: str
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
    "Return exactly one result per input job, echoing its job_url exactly."
)


def build_match_prompt(candidate: MatchingProfile, jobs_for_matching: list[JobForMatching]) -> str:
    candidate_json = candidate.model_dump_json(indent=2)
    jobs_blocks = []
    for j in jobs_for_matching:
        jobs_blocks.append(
            f"job_url: {j.job_url}\n"
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
        return {r.job_url: r for r in batch.results}

    def run(
        self,
        candidate_id: str,
        candidate: MatchingProfile,
        candidate_langs: list[str],
        jobs: list[JobOffer],
        raw_jobs_by_url: dict[str, RawJob],
    ) -> list[MatchResult]:
        results, rejected = self._load_existing(candidate_id)
        already_done = {r.job_url for r in results} | {r.job_url for r in rejected}

        to_score: list[JobOffer] = []
        for job in jobs:
            if job.job_url in already_done:
                continue
            reason = apply_hard_filters(job, candidate_langs)
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