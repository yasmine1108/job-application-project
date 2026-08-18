from config.settings import Settings
from src.ai_modules.cover_letter import generate_cover_letter
from src.llm.fallback import FallbackLLM
from src.llm.gemini_provider import GeminiProvider
from src.llm.groq_provider import GroqProvider
from src.matchers.matcher import Matcher
from src.data_helpers import (
    get_job_offer_by_id,
    get_match_result_by_job_id_from_file,
    get_raw_job_by_id,
    load_candidate_profile_from_example,
    load_matching_profile_from_example,
)

def test_cover_letter_generation():
    raw_job = get_raw_job_by_id("2032767", "data/outputs/tanitjobs_raw_job_list.json")
    job_offer = get_job_offer_by_id("2032767", "data/outputs/tanitjobs_structured_jobs.json")
    candidate = load_candidate_profile_from_example("data/outputs/example_cv_profile.json")
    fallback_llm = FallbackLLM([
        GeminiProvider(Settings.GEMINI_API_KEY, "gemini-3.5-flash"),
        GeminiProvider(Settings.GEMINI_API_KEY, "gemini-3.5-flash-lite"),
        GroqProvider(Settings.GROQ_API_KEY, "openai/gpt-oss-120b"),
        GroqProvider(Settings.GROQ_API_KEY, "openai/gpt-oss-20b"),
    ])
    match_result = get_match_result_by_job_id_from_file(
        job_id="2032767",
        path="data/outputs/tanitjobs_match_results.json",
        candidate_id=candidate.candidate_id,)
    
    cover_letter_draft = generate_cover_letter(
        candidate=candidate,
        job_offer=job_offer,
        match_result=match_result,
        company=raw_job.company,
        job_description=raw_job.description,
        llm=fallback_llm,
        min_score=0.5
    )
    print("Generated cover letter draft:", cover_letter_draft)