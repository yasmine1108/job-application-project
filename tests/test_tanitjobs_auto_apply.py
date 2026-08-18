from agent_project.config.settings import Settings
from agent_project.src.llm.fallback import FallbackLLM
from agent_project.src.llm.gemini_provider import GeminiProvider
from agent_project.src.llm.groq_provider import GroqProvider
from src.scrapers.tanitjobs import TanitJobsScraper
from src.data_helpers import (
    get_raw_job_by_id,
    get_job_offer_by_id,
    get_match_result_by_job_id_from_file,
    load_candidate_profile_from_example,
)
from agent_project.src.application_logging import ApplicationLog



def test_tanitjobs_auto_apply_dry_run(tmp_path):
    # use same candidate and job as cover letter test
    candidate = load_candidate_profile_from_example("data/outputs/example_cv_profile.json")
    raw_job = get_raw_job_by_id("2032767", "data/outputs/tanitjobs_raw_job_list.json")
    job_offer = get_job_offer_by_id("2032767", "data/outputs/tanitjobs_structured_jobs.json")
    match_result = get_match_result_by_job_id_from_file(
        job_id="2032767",
        path="data/outputs/tanitjobs_match_results.json",
        candidate_id=candidate.candidate_id,
    )

    scraper = TanitJobsScraper()

    fallback_llm = FallbackLLM([
        GeminiProvider(Settings.GEMINI_API_KEY, "gemini-3.5-flash"),
        GeminiProvider(Settings.GEMINI_API_KEY, "gemini-3.5-flash-lite"),
        GroqProvider(Settings.GROQ_API_KEY, "openai/gpt-oss-120b"),
        GroqProvider(Settings.GROQ_API_KEY, "openai/gpt-oss-20b"),
    ])
    log = scraper.auto_apply(
        job_url=raw_job.job_url,
        candidate=candidate,
        cv_path=str("data/outputs/example_cv.pdf"),
        llm=fallback_llm,
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
    assert log.payload["cv_path"] == str("data/outputs/example_cv.pdf")
    assert "Dear hiring team" in (log.payload["cover_letter"] or "")
