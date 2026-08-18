"""
Candidate identity.

candidate_id is a synthetic, stable identifier -- NOT derived from email.
Email is mutable, optional-until-the-GUI-fills-it, and case-sensitive by
accident; none of those are properties you want in something used as a
join key across MatchResult / RejectedMatch / ApplicationLog.

Usage:
- Call ensure_candidate_id() once, right after extraction, before the
  profile is cached to disk. If a cached profile already exists for this
  CV, its candidate_id is reused so identity survives re-runs.
- Call ensure_mandatory_contact_fields() before matching/applying -- not
  at extraction time, since a missing email at extraction is expected to
  be filled in later via the GUI, not an extraction failure.
"""

import json
import uuid
from pathlib import Path

from src.models import CandidateProfile


class MissingCandidateContactInfoError(ValueError):
    pass


def ensure_candidate_id(candidate: CandidateProfile, cache_path: Path) -> CandidateProfile:
    if candidate.candidate_id:
        return candidate  # already set -- e.g. this profile was loaded, not freshly extracted

    existing_id = None
    if cache_path.exists():
        try:
            with cache_path.open("r", encoding="utf-8") as f:
                existing_data = json.load(f)
            existing_id = existing_data.get("candidate_id")
        except json.JSONDecodeError:
            existing_id = None

    candidate.candidate_id = existing_id or str(uuid.uuid4())
    return candidate


def ensure_mandatory_contact_fields(candidate: CandidateProfile) -> None:
    email = candidate.personal_information.email
    if not email or not email.strip():
        raise MissingCandidateContactInfoError(
            "candidate.personal_information.email is required before matching/applying. "
            "If this fires, the GUI needs to collect it before this candidate can be processed."
        )
