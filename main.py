# # from src.data_helpers import get_job_offer_by_id, get_raw_job_by_id, load_matching_profile_from_example
import json

from src.pipeline import run_pipeline_for_candidate
from src.models import CandidateProfile
# from src.models_job import JobOffer, RawJob
from src.matchers.matcher import CandidatePreferences, Matcher
from config.settings import Settings
from src.llm.fallback import FallbackLLM
from src.llm.gemini_provider import GeminiProvider
from src.llm.groq_provider import GroqProvider
from src.ai_modules.job_offer_extractor import JobOfferExtractor
# # from src.ai_modules.cv_extractor import CVExtractor
# # from src.ai_modules.cv_parser import CVParser
from src.scrapers.tanitjobs import TanitJobsScraper
from src.scrapers.linkedin import LinkedInScraper
from src.scrapers.job_board_scraper import register_scraper

# from langchain_ollama import ChatOllama

# llm = ChatOllama(
#     model="qwen2.5:7b",
#     temperature=0
# )
# print(llm.model)

def load_candidate(path: str) -> CandidateProfile:
    with open(path, "r", encoding="utf-8") as f:
        return CandidateProfile.model_validate(json.load(f))


# def load_jobs(structured_path: str, raw_path: str) -> tuple[list[JobOffer], dict[str, RawJob]]:
#     with open(structured_path, "r", encoding="utf-8") as f:
#         jobs = [JobOffer.model_validate(item) for item in json.load(f)]
#     with open(raw_path, "r", encoding="utf-8") as f:
#         raw_jobs = [RawJob.model_validate(item) for item in json.load(f)]
#     raw_by_url = {r.job_url: r for r in raw_jobs}
#     return jobs, raw_by_url

if __name__ == "__main__":

#     # bot_linkedin = LinkedInScraper()
    
#     # bot_linkedin.start_browser()  
#     # # bot_linkedin.ensure_logged_in()          
#     # # bot_linkedin.search_and_collect_links("Python Developer")
#     # bot_linkedin.extract_job_list()
#     # bot_linkedin.close_browser()


#     # tanitjobs_scraper = TanitJobsScraper()
#     # tanitjobs_scraper.start_browser()
#     # tanitjobs_scraper.ensure_logged_in()
#     # tanitjobs_scraper.search_and_collect_links("data engineer")
#     # tanitjobs_scraper.extract_job_list()
#     # tanitjobs_scraper.close_browser()

#     # cv_parser = CVParser("example_cv.pdf")
#     # document = cv_parser.extract_text()
#     # extractor = CVExtractor(llm=llm, debug=True)
#     # candidate = extractor.extract(document)

    if not Settings.GEMINI_API_KEY and not Settings.GROQ_API_KEY:
        raise RuntimeError("No API key configured. Set GEMINI_API_KEY and/or GROQ_API_KEY in your environment before running the extractor.")

    fallback_llm = FallbackLLM([
        GeminiProvider(Settings.GEMINI_API_KEY, "gemini-3.5-flash"),
        GeminiProvider(Settings.GEMINI_API_KEY, "gemini-3.5-flash-lite"),
        GroqProvider(Settings.GROQ_API_KEY, "openai/gpt-oss-120b"),
        GroqProvider(Settings.GROQ_API_KEY, "openai/gpt-oss-20b"),
    ])
    job_extractor = JobOfferExtractor(
        llm=fallback_llm,
        output_path="data/outputs/tanitjobs_structured_jobs.json",
        batch_size=8,
    )
#     # job_extractor.extract_jobs_from_file()

#     # job_offer = get_job_offer_by_id("4413017677")
#     # raw_job = get_raw_job_by_id("4413017677")
#     # matching = load_matching_profile_from_example()
#     # matcher: Matcher = Matcher()
#     # print(matcher.match(job_offer,raw_job,matching,["full-time"]))

    candidate_profile = load_candidate("data/outputs/example_cv_profile.json")
    preferences = CandidatePreferences(
        country="Tunisia",
        governorate="Tunis",
        max_commute_distance_km=100,
        willing_to_relocate=False,
    )
    register_scraper("tanitjobs.com", TanitJobsScraper)
    register_scraper("linkedin.com", LinkedInScraper)
    run_pipeline_for_candidate(
        candidate=candidate_profile,
        keyword="AI Engineer",
        preferences=preferences,
        llm=fallback_llm,
        job_offer_extractor=job_extractor,  # Replace with actual job offer extractor
        matches_output_path="data/outputs/tanitjobs_match_results.json",
        applications_log_path="data/outputs/tanitjobs_applications.json",
        cv_path="data/cv/example_cv.pdf",
        board_domains=["tanitjobs.com"],  # Specify the job board domains to scrape
    )

#     # jobs, raw_by_url = load_jobs(
#     #     "data/outputs/linkedin_structured_jobs.json",
#     #     "data/outputs/linkedin_raw_job_list.json",
#     # )

#     # matcher = Matcher(
#     #     llm=fallback_llm,
#     #     output_path="data/outputs/v2_linkedin_match_results.json",
#     #     batch_size=8,
#     # )

#     # results = matcher.run(
#     #     candidate_id=candidate_profile.personal_information.email,
#     #     candidate=matching_profile,
#     #     candidate_langs=matching_profile.spoken_languages,
#     #     jobs=jobs,
#     #     raw_jobs_by_url=raw_by_url,
#     #     preferences=preferences,
#     # )

#     # for r in sorted(results, key=lambda r: r.overall_score, reverse=True):
#     #     print(f"{r.overall_score:.2f} | {r.judgment.summary[:80]} | {r.job_url}")


# from config.settings import Settings
# from src.llm.fallback import FallbackLLM
# from src.llm.gemini_provider import GeminiProvider
# from src.llm.groq_provider import GroqProvider
# from src.scrapers.tanitjobs import TanitJobsScraper
# from src.data_helpers import (
#     get_raw_job_by_id,
#     get_job_offer_by_id,
#     get_match_result_by_job_id_from_file,
#     load_candidate_profile_from_example,
# )
# from src.application_logging import ApplicationLog



# def test_tanitjobs_auto_apply_dry_run(tmp_path):
#     # use same candidate and job as cover letter test
#     candidate = load_candidate_profile_from_example("data/outputs/example_cv_profile.json")
#     raw_job = get_raw_job_by_id("2032767", "data/outputs/tanitjobs_raw_job_list.json")
#     job_offer = get_job_offer_by_id("2032767", "data/outputs/tanitjobs_structured_jobs.json")
#     match_result = get_match_result_by_job_id_from_file(
#         job_id="2032767",
#         path="data/outputs/tanitjobs_match_results.json",
#         candidate_id=candidate.candidate_id,
#     )

#     scraper = TanitJobsScraper()
#     scraper.start_browser()
#     scraper.ensure_logged_in()
#     fallback_llm = FallbackLLM([
#         GeminiProvider(Settings.GEMINI_API_KEY, "gemini-3.5-flash"),
#         GeminiProvider(Settings.GEMINI_API_KEY, "gemini-3.5-flash-lite"),
#         GroqProvider(Settings.GROQ_API_KEY, "openai/gpt-oss-120b"),
#         GroqProvider(Settings.GROQ_API_KEY, "openai/gpt-oss-20b"),
#     ])
#     log = scraper.auto_apply(
#         job_url=raw_job.job_url,
#         candidate=candidate,
#         cv_path=str("data/cv/example_cv.pdf"),
#         llm=fallback_llm,
#         match_result=match_result,
#         job_offer=job_offer,
#         raw_job=raw_job,
#         dry_run=True,
#     )

#     assert isinstance(log, ApplicationLog)
#     assert log.dry_run is True
#     assert log.submitted is False
#     assert log.payload["name"] == candidate.personal_information.full_name
#     assert log.payload["email"] == candidate.personal_information.email
#     assert log.payload["phone"] == candidate.personal_information.phone
#     assert log.payload["cv_path"] == str("data/cv/example_cv.pdf")
#     assert "Dear hiring team" in (log.payload["cover_letter"] or "")
#     scraper.close_browser()
# if __name__ == "__main__":
#     test_tanitjobs_auto_apply_dry_run(tmp_path="data/outputs")