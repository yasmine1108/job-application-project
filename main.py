# from src.data_helpers import get_job_offer_by_id, get_raw_job_by_id, load_matching_profile_from_example
# from src.matchers.matcher import Matcher
# from src.ai_modules.job_offer_extractor import GeminiJobExtractor
# from src.ai_modules.cv_extractor import CVExtractor
# from src.ai_modules.cv_parser import CVParser
from src.scrapers.tanitjobs import TanitJobsScraper
# from src.scrapers.linkedin import LinkedInScraper

# from langchain_ollama import ChatOllama

# llm = ChatOllama(
#     model="qwen2.5:7b",
#     temperature=0
# )
# print(llm.model)

if __name__ == "__main__":

    # bot_linkedin = LinkedInScraper()
    
    # bot_linkedin.start_browser()  
    # # bot_linkedin.ensure_logged_in()          
    # # bot_linkedin.search_and_collect_links("Python Developer")
    # bot_linkedin.extract_job_list()
    # bot_linkedin.close_browser()


    tanitjobs_scraper = TanitJobsScraper()
    tanitjobs_scraper.start_browser()
    # tanitjobs_scraper.ensure_logged_in()
    # tanitjobs_scraper.search_and_collect_links("data engineer")
    tanitjobs_scraper.extract_job_list()
    tanitjobs_scraper.close_browser()

    # cv_parser = CVParser("example_cv.pdf")
    # document = cv_parser.extract_text()
    # extractor = CVExtractor(llm=llm, debug=False)
    # candidate = extractor.extract(document)

    # job_extractor = GeminiJobExtractor()
    # job_extractor.extract_jobs_from_file()   

    # job_offer = get_job_offer_by_id("4413017677")
    # raw_job = get_raw_job_by_id("4413017677")
    # matching = load_matching_profile_from_example()
    # matcher: Matcher = Matcher()
    # print(matcher.match(job_offer,raw_job,matching,["full-time"]))


# run_matching.py
# import json
# from pathlib import Path

# from config.settings import Settings
# from src.llm.gemini_provider import GeminiProvider
# from src.llm.groq_provider import GroqProvider
# from src.llm.fallback import FallbackLLM
# from src.models import CandidateProfile
# from src.models_job import RawJob, JobOffer
# from src.ai_modules.matcher import Matcher


# def load_candidate(path: str) -> CandidateProfile:
#     with open(path, "r", encoding="utf-8") as f:
#         return CandidateProfile.model_validate(json.load(f))


# def load_jobs(structured_path: str, raw_path: str) -> tuple[list[JobOffer], dict[str, RawJob]]:
#     with open(structured_path, "r", encoding="utf-8") as f:
#         jobs = [JobOffer.model_validate(item) for item in json.load(f)]
#     with open(raw_path, "r", encoding="utf-8") as f:
#         raw_jobs = [RawJob.model_validate(item) for item in json.load(f)]
#     raw_by_url = {r.job_url: r for r in raw_jobs}
#     return jobs, raw_by_url


# if __name__ == "__main__":
#     llm = FallbackLLM([
#         GeminiProvider(Settings.GEMINI_API_KEY, Settings.GEMINI_MODEL_NAME),
#         GroqProvider(Settings.GROQ_API_KEY, Settings.GROQ_MODEL_NAME),
#     ])

#     candidate_profile = load_candidate("data/outputs/v2_example_cv_profile.json")
#     matching_profile = candidate_profile.get_matching_profile()

#     jobs, raw_by_url = load_jobs(
#         "data/outputs/linkedin_structured_jobs.json",
#         "data/outputs/linkedin_raw_job_list.json",
#     )

#     matcher = Matcher(
#         llm=llm,
#         output_path="data/outputs/match_results.json",
#         batch_size=8,
#     )

#     results = matcher.run(
#         candidate_id="yasmine_chakroun",
#         candidate=matching_profile,
#         candidate_langs=[],  # wire up candidate.spoken_languages here once populated
#         jobs=jobs,
#         raw_jobs_by_url=raw_by_url,
#     )

#     for r in sorted(results, key=lambda r: r.overall_score, reverse=True):
#         print(f"{r.overall_score:.2f} | {r.judgment.summary[:80]} | {r.job_url}")