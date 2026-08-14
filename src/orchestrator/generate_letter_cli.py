"""
Entry point for the AI environment (langchain, FallbackLLM, pydantic models).
Runs as a subprocess launched with the AI venv's python interpreter.

Contract: reads one JSON object from stdin, writes one JSON object to stdout.
No shared classes crossing the process boundary -- only plain data.

Usage (from the orchestrator, in a different venv):
    /path/to/ai-venv/bin/python -m src.ai_env.generate_letter_cli < input.json > output.json
"""

import json
import sys

from src.models import CandidateProfile
from src.matchers.matcher import MatchResult
from src.models_job import JobOffer
from src.llm.fallback import FallbackLLM
from src.llm.providers import build_default_providers  # however you construct your real providers
from src.cover_letter import generate_cover_letter


def main() -> None:
    raw_input = json.load(sys.stdin)

    candidate = CandidateProfile.model_validate(raw_input["candidate"])
    match_result = MatchResult.model_validate(raw_input["match_result"])
    job_offer = JobOffer.model_validate(raw_input["job_offer"])
    company = raw_input["company"]
    job_description = raw_input.get("job_description")
    min_score = raw_input.get("min_score", 0.5)

    llm = FallbackLLM(build_default_providers())

    letter = generate_cover_letter(
        candidate=candidate,
        match_result=match_result,
        job_offer=job_offer,
        company=company,
        job_description=job_description,
        llm=llm,
        min_score=min_score,
    )

    json.dump({"cover_letter": letter}, sys.stdout)


if __name__ == "__main__":
    main()
