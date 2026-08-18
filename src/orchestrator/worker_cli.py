"""
Worker entry point -- everything except LangGraph lives here: SeleniumBase/
Playwright, google-genai, groq, langchain-core/langchain-ollama (for
CVExtractor), pydantic models, matching, cover letter generation, applying.

Runs as a subprocess launched with the WORKER venv's python interpreter.
This is now the *only* process boundary in the pipeline -- the orchestrator
(LangGraph, separate venv) calls this script; everything on this side stays
in-process, no further subprocess hops.

Contract: reads one JSON object from stdin, writes one JSON object to stdout.
"""

import json
import sys

from src.models import CandidateProfile
from src.matchers.matcher import MatchResult
from src.models_job import JobOffer, RawJob
from src.llm.providers import build_default_fallback_llm
from src.scrapers.tanitjobs import TanitJobsScraper


def apply_to_job(
    job_url: str,
    candidate: CandidateProfile,
    match_result: MatchResult,
    job_offer: JobOffer,
    raw_job: RawJob,
    cv_path: str,
    dry_run: bool = True,
) -> dict:
    """auto_apply already generates the cover letter internally (it calls
    generate_cover_letter itself) and already saves the ApplicationLog
    (via self._save_application_log). Nothing to duplicate here -- just
    provide the LLM and hand off to the scraper's own session lifecycle."""
    llm = build_default_fallback_llm()

    scraper = TanitJobsScraper()
    scraper.start_browser()
    scraper.ensure_logged_in()
    try:
        log = scraper.auto_apply(
            job_url=job_url,
            candidate=candidate,
            cv_path=cv_path,
            llm=llm,
            match_result=match_result,
            job_offer=job_offer,
            raw_job=raw_job,
            dry_run=dry_run,
        )
    finally:
        scraper.close_browser()

    return log.model_dump(mode="json")


def main() -> None:
    raw_input = json.load(sys.stdin)

    candidate = CandidateProfile.model_validate(raw_input["candidate"])
    match_result = MatchResult.model_validate(raw_input["match_result"])
    job_offer = JobOffer.model_validate(raw_input["job_offer"])
    raw_job = RawJob.model_validate(raw_input["raw_job"])

    result = apply_to_job(
        job_url=raw_input["job_url"],
        candidate=candidate,
        match_result=match_result,
        job_offer=job_offer,
        raw_job=raw_job,
        cv_path=raw_input["cv_path"],
        dry_run=raw_input.get("dry_run", True),
    )

    json.dump(result, sys.stdout)


if __name__ == "__main__":
    main()