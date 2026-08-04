import json
from pathlib import Path
import sys

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.models import CandidateProfile, MatchingProfile
from src.models_job import JobOffer, RawJob


_BASE_DIR = Path(__file__).resolve().parents[1]


def _load_json_data(relative_path: str):
    path = _BASE_DIR / relative_path
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def get_job_offer_by_id(job_id: str) -> JobOffer:
    """Load a structured job offer from the LinkedIn JSON output by job_id."""
    jobs = _load_json_data("data/outputs/linkedin_structured_jobs.json")
    for item in jobs:
        if str(item.get("job_id")) == str(job_id):
            return JobOffer.model_validate(item)
    raise LookupError(f"No job offer found for job_id={job_id}")


def get_raw_job_by_id(job_id: str) -> RawJob:
    """Load a raw scraped job posting from the LinkedIn JSON output by job_id."""
    jobs = _load_json_data("data/outputs/linkedin_raw_job_list.json")
    for item in jobs:
        if str(item.get("job_id")) == str(job_id):
            return RawJob.model_validate(item)
    raise LookupError(f"No raw job found for job_id={job_id}")


def load_candidate_profile_from_example() -> CandidateProfile:
    """Load the sample CV profile JSON as a CandidateProfile."""
    payload = _load_json_data("data/outputs/v2_example_cv_profile.json")
    return CandidateProfile.model_validate(payload)


def load_matching_profile_from_example() -> MatchingProfile:
    """Load the sample CV profile and convert it into a MatchingProfile."""
    candidate_profile = load_candidate_profile_from_example()
    return candidate_profile.get_matching_profile()
