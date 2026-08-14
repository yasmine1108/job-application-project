from src.scrapers.tanitjobs import TanitJobsScraper
from src.data_helpers import (
    get_raw_job_by_id,
    get_job_offer_by_id,
    get_match_result_by_job_id_from_file,
    load_candidate_profile_from_example,
)
from src.scrapers.application_logging import ApplicationLog



def test_tanitjobs_auto_apply_dry_run(tmp_path):
    # use same candidate and job as cover letter test
    candidate = load_candidate_profile_from_example("data/outputs/example_cv_profile.json")
    raw_job = get_raw_job_by_id("2032767", "data/outputs/tanitjobs_raw_job_list.json")
    job_offer = get_job_offer_by_id("2032767", "data/outputs/tanitjobs_structured_jobs.json")
    match_result = get_match_result_by_job_id_from_file(
        job_id="2032767",
        path="data/outputs/tanitjobs_match_results.json",
        candidate_id=candidate.personal_information.email,
    )

    scraper = TanitJobsScraper()
    # attach fake page and set output path to tmp
    scraper.page = FakePage()
    scraper.applications_output_path = tmp_path / "apps.json"

    # create a dummy cv file
    cv_path = tmp_path / "cv.pdf"
    cv_path.write_text("dummy cv content")

    llm = FakeLLM()

    log = scraper.auto_apply(
        job_url=raw_job.job_url,
        candidate=candidate,
        cv_path=str(cv_path),
        llm=llm,
        match_result=match_result,
        job_offer=job_offer,
        raw_job=raw_job,
        dry_run=True,
    )

    assert isinstance(log, ApplicationLog)
    assert log.dry_run is True
    assert log.submitted is False
    assert log.payload["name"] == candidate.personal_information.full_name
    assert log.payload["email"] == candidate.personal_information.email
    assert log.payload["phone"] == candidate.personal_information.phone
    assert log.payload["cv_path"] == str(cv_path)
    assert "Dear hiring team" in (log.payload["cover_letter"] or "")
