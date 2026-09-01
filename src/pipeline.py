"""
End-to-end pipeline for one candidate, one search keyword.

Design:
- Objects (list[RawJob], list[JobOffer], list[MatchResult]) are passed
  directly between steps in memory. No step reads a file another step
  just wrote.
- JSON files still get written, but only where they already were:
  - scraper.search_and_collect_links / extract_job_list still persist
    internally (crash-recovery for long scraping runs, and de-dup of
    already-seen links -- this is durability, not step handoff).
  - Matcher._save persists after every batch (same reason).
  - ApplicationLog persists every apply attempt.
- "Already applied" is checked once, up front, the same way Matcher
  already checks "already scored" via its own already_done set.
"""

from pathlib import Path

from src.models import CandidateProfile
from src.matchers.matcher import Matcher, CandidatePreferences, MatchResult
from src.models_job import JobOffer, RawJob
from src.llm.fallback import FallbackLLM
from src.candidate_identity import ensure_mandatory_contact_fields
from src.application_logging import load_application_logs
from src.scrapers.job_board_scraper import SCRAPER_REGISTRY, get_scraper_for_url


def run_pipeline_for_candidate(
    candidate: CandidateProfile,
    keyword: str,
    preferences: CandidatePreferences,
    llm: FallbackLLM,
    job_offer_extractor,  
    matches_output_path: str | Path,
    applications_log_path: str | Path,
    cv_path: str,
    board_domains: list[str] | None = None,  # None = search every registered board
    dry_run: bool = True,
    high_score_threshold: float = 0.75,
    mid_score_threshold: float = 0.5,
) -> dict:
    ensure_mandatory_contact_fields(candidate)
    matching_profile = candidate.get_matching_profile()

    # --- Step 1+2: scrape + extract raw jobs, across the requested boards ---
    scraper_classes = (
        [cls for domain, cls in SCRAPER_REGISTRY.items() if domain in board_domains]
        if board_domains
        else list(SCRAPER_REGISTRY.values())
    )

    all_raw_jobs: list[RawJob] = []
    for scraper_cls in scraper_classes:
        scraper = scraper_cls()
        scraper.start_browser()
        scraper.ensure_logged_in()
        try:
            collected_links = scraper.search_and_collect_links(keyword) 
            raw_jobs = scraper.extract_job_list(collected_links)      
        finally:
            scraper.close_browser()
        all_raw_jobs.extend(raw_jobs)

    raw_jobs_by_url: dict[str, RawJob] = {j.job_url: j for j in all_raw_jobs if j.job_url}

    # --- Step 3: structured extraction ---

    job_offers: list[JobOffer] = job_offer_extractor.extract_jobs(all_raw_jobs)
    job_offers_by_url: dict[str, JobOffer] = {j.job_url: j for j in job_offers}

    # --- Step 4: matching (Matcher.run already returns in-memory results;
    # its internal _save calls are its own crash-recovery, untouched) ---
    matcher = Matcher(llm=llm, output_path=matches_output_path)
    match_results = matcher.run(
        candidate_id=candidate.candidate_id,
        candidate=matching_profile,
        candidate_langs=matching_profile.spoken_languages,
        jobs=job_offers,
        raw_jobs_by_url=raw_jobs_by_url,
        preferences=preferences,
    )
    match_results = [
    r for r in match_results
    if r.job_url in raw_jobs_by_url and r.job_url in job_offers_by_url
    ]
    # --- Step 5: tiering, with an "already applied" gate up front ---
    already_applied_urls = {
        log.job_url
        for log in load_application_logs(applications_log_path, candidate.candidate_id)
        if log.submitted  # dry runs don't block retrying; real submissions do
    }

    to_auto_apply: list[MatchResult] = []
    to_confirm: list[MatchResult] = []
    discarded: list[MatchResult] = []

    for r in match_results:
        if r.job_url in already_applied_urls:
            continue
        if r.overall_score >= high_score_threshold:
            to_auto_apply.append(r)
        elif r.overall_score >= mid_score_threshold:
            to_confirm.append(r)
        else:
            discarded.append(r)

    # --- Step 6: auto-apply the high-confidence tier ---
    applied_logs = []
    for r in to_auto_apply:
        raw_job = raw_jobs_by_url.get(r.job_url)
        job_offer = job_offers_by_url.get(r.job_url)
        if raw_job is None or job_offer is None:
            print(
                f"WARNING: {r.job_url} was matched in a previous run but wasn't "
                "scraped/extracted in this run -- skipping auto-apply. Re-run a "
                "search that surfaces this job again to retry it."
            )
            continue
        scraper = get_scraper_for_url(r.job_url)
        scraper.start_browser()
        scraper.ensure_logged_in()
        try:
            log = scraper.auto_apply(
                job_url=r.job_url,
                candidate=candidate,
                cv_path=cv_path,
                llm=llm,
                match_result=r,
                job_offer=job_offers_by_url[r.job_url],
                raw_job=raw_jobs_by_url[r.job_url],
                dry_run=dry_run,
            )
        finally:
            scraper.close_browser()
        applied_logs.append(log)



    return {
        "auto_applied": applied_logs,
        "to_confirm": to_confirm,   
        "discarded": discarded,
    }
