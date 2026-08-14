# from src.data_helpers import get_job_offer_by_id, get_raw_job_by_id, load_matching_profile_from_example
import json

from src.models import CandidateProfile
from src.models_job import JobOffer, RawJob
from src.matchers.matcher import CandidatePreferences, Matcher
from config.settings import Settings
from src.llm.fallback import FallbackLLM
from src.llm.gemini_provider import GeminiProvider
from src.llm.groq_provider import GroqProvider
# from src.ai_modules.job_offer_extractor import JobOfferExtractor
# from src.ai_modules.cv_extractor import CVExtractor
# from src.ai_modules.cv_parser import CVParser
# from src.scrapers.tanitjobs import TanitJobsScraper
# from src.scrapers.linkedin import LinkedInScraper

from langchain_ollama import ChatOllama

llm = ChatOllama(
    model="qwen2.5:7b",
    temperature=0
)
print(llm.model)

def load_candidate(path: str) -> CandidateProfile:
    with open(path, "r", encoding="utf-8") as f:
        return CandidateProfile.model_validate(json.load(f))


def load_jobs(structured_path: str, raw_path: str) -> tuple[list[JobOffer], dict[str, RawJob]]:
    with open(structured_path, "r", encoding="utf-8") as f:
        jobs = [JobOffer.model_validate(item) for item in json.load(f)]
    with open(raw_path, "r", encoding="utf-8") as f:
        raw_jobs = [RawJob.model_validate(item) for item in json.load(f)]
    raw_by_url = {r.job_url: r for r in raw_jobs}
    return jobs, raw_by_url

if __name__ == "__main__":

    # bot_linkedin = LinkedInScraper()
    
    # bot_linkedin.start_browser()  
    # # bot_linkedin.ensure_logged_in()          
    # # bot_linkedin.search_and_collect_links("Python Developer")
    # bot_linkedin.extract_job_list()
    # bot_linkedin.close_browser()


    # tanitjobs_scraper = TanitJobsScraper()
    # tanitjobs_scraper.start_browser()
    # tanitjobs_scraper.ensure_logged_in()
    # tanitjobs_scraper.search_and_collect_links("data engineer")
    # tanitjobs_scraper.extract_job_list()
    # tanitjobs_scraper.close_browser()

    # cv_parser = CVParser("example_cv.pdf")
    # document = cv_parser.extract_text()
    # extractor = CVExtractor(llm=llm, debug=True)
    # candidate = extractor.extract(document)

    if not Settings.GEMINI_API_KEY and not Settings.GROQ_API_KEY:
        raise RuntimeError("No API key configured. Set GEMINI_API_KEY and/or GROQ_API_KEY in your environment before running the extractor.")

    fallback_llm = FallbackLLM([
        GeminiProvider(Settings.GEMINI_API_KEY, "gemini-3.5-flash"),
        GeminiProvider(Settings.GEMINI_API_KEY, "gemini-3.5-flash-lite"),
        GroqProvider(Settings.GROQ_API_KEY, "openai/gpt-oss-120b"),
        GroqProvider(Settings.GROQ_API_KEY, "openai/gpt-oss-20b"),
    ])
    # job_extractor = JobOfferExtractor(
    #     llm=fallback_llm,
    #     input_path="data/outputs/tanitjobs_raw_job_list.json",
    #     output_path="data/outputs/tanitjobs_structured_jobs.json",
    #     batch_size=8,
    # )
    # job_extractor.extract_jobs_from_file()

    # job_offer = get_job_offer_by_id("4413017677")
    # raw_job = get_raw_job_by_id("4413017677")
    # matching = load_matching_profile_from_example()
    # matcher: Matcher = Matcher()
    # print(matcher.match(job_offer,raw_job,matching,["full-time"]))

    candidate_profile = load_candidate("data/outputs/example_cv_profile.json")
    matching_profile = candidate_profile.get_matching_profile()
    preferences = CandidatePreferences(
        country="Tunisia",
        governorate="Tunis",
        max_commute_distance_km=100,
        willing_to_relocate=False,
    )

    jobs, raw_by_url = load_jobs(
        "data/outputs/linkedin_structured_jobs.json",
        "data/outputs/linkedin_raw_job_list.json",
    )

    matcher = Matcher(
        llm=fallback_llm,
        output_path="data/outputs/v2_linkedin_match_results.json",
        batch_size=8,
    )

    results = matcher.run(
        candidate_id=candidate_profile.personal_information.email,
        candidate=matching_profile,
        candidate_langs=matching_profile.spoken_languages,
        jobs=jobs,
        raw_jobs_by_url=raw_by_url,
        preferences=preferences,
    )

    for r in sorted(results, key=lambda r: r.overall_score, reverse=True):
        print(f"{r.overall_score:.2f} | {r.judgment.summary[:80]} | {r.job_url}")


