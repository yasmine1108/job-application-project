import json
from pathlib import Path
import sys

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.models import CandidateProfile, MatchingProfile
from src.models_job import JobOffer, RawJob
from src.matchers.matcher import MatchResult


_BASE_DIR = Path(__file__).resolve().parents[1]


def _load_json_data(relative_path: str):
    path = _BASE_DIR / relative_path
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def get_job_offer_by_id(job_id: str,path: str) -> JobOffer:
    """Load a structured job offer from the LinkedIn JSON output by job_id."""
    jobs = _load_json_data(path)
    for item in jobs:
        if str(item.get("job_id")) == str(job_id):
            return JobOffer.model_validate(item)
    raise LookupError(f"No job offer found for job_id={job_id}")


def get_raw_job_by_id(job_id: str,path: str) -> RawJob:
    """Load a raw scraped job posting from the LinkedIn JSON output by job_id."""
    jobs = _load_json_data(path)
    for item in jobs:
        if str(item.get("job_id")) == str(job_id):
            return RawJob.model_validate(item)
    raise LookupError(f"No raw job found for job_id={job_id}")


def load_candidate_profile_from_example(path: str = "data/outputs/example_cv_profile.json") -> CandidateProfile:
    """Load the sample CV profile JSON as a CandidateProfile."""
    payload = _load_json_data(path)
    return CandidateProfile.model_validate(payload)


def load_matching_profile_from_example(path: str = "data/outputs/example_cv_profile.json") -> MatchingProfile:
    """Load the sample CV profile and convert it into a MatchingProfile."""
    candidate_profile = load_candidate_profile_from_example(path)
    return candidate_profile.get_matching_profile()


def get_match_result_by_job_id_from_file(job_id: str, path: str = "data/outputs/linkedin_match_results.json", candidate_id: str | None = None) -> MatchResult:
    """Load a MatchResult from a results file by the judgment.job_id value.

    If `candidate_id` is provided, only return results for that candidate.
    """
    payload = _load_json_data(path)
    for item in payload.get("results", []):
        judgment = item.get("judgment", {})
        if str(judgment.get("job_id")) == str(job_id):
            if candidate_id is None or str(item.get("candidate_id")) == str(candidate_id):
                return MatchResult.model_validate(item)
    raise LookupError(f"No MatchResult found for job_id={job_id}" + (f" and candidate_id={candidate_id}" if candidate_id else ""))
