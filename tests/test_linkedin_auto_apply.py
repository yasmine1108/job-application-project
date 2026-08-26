import os

import pytest

from src.application_logging import ApplicationLog
from src.data_helpers import (
    get_job_offer_by_id,
    get_match_result_by_job_id_from_file,
    get_raw_job_by_id,
    load_candidate_profile_from_example,
)
from src.scrapers.linkedin import LinkedInScraper


@pytest.mark.skipif(
    os.getenv("RUN_LINKEDIN_LIVE_TESTS") != "1",
    reason="Set RUN_LINKEDIN_LIVE_TESTS=1 to run against LinkedIn",
)
def test_linkedin_auto_apply_dry_run_for_given_url():
    job_id = "4427131133"
    job_url = f"https://www.linkedin.com/jobs/view/{job_id}/"
    candidate = load_candidate_profile_from_example(
        "data/outputs/example_cv_profile.json"
    )
    raw_job = get_raw_job_by_id(
        job_id, "data/outputs/linkedin_raw_job_list.json"
    )
    job_offer = get_job_offer_by_id(
        job_id, "data/outputs/linkedin_structured_jobs.json"
    )
    match_result = get_match_result_by_job_id_from_file(
        job_id,
        "data/outputs/linkedin_match_results.json",
        candidate_id=candidate.candidate_id,
    )

    assert raw_job.job_url == job_url
    assert job_offer.job_url == job_url
    assert match_result.job_url == job_url

    scraper = LinkedInScraper()
    scraper.start_browser()
    try:
        scraper.ensure_logged_in()
        log = scraper.auto_apply(
            job_url=job_url,
            candidate=candidate,
            cv_path="data/outputs/example_cv.pdf",
            llm=None,
            match_result=match_result,
            job_offer=job_offer,
            raw_job=raw_job,
            dry_run=True,
        )
    finally:
        scraper.close_browser()

    assert isinstance(log, ApplicationLog)
    assert log.job_url == job_url
    assert log.candidate_id == candidate.candidate_id
    assert log.dry_run is True
    assert log.submitted is False
    assert log.payload["job_url"] == job_url