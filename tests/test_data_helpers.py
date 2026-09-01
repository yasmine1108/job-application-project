from src.data_helpers import (
    get_job_offer_by_id,
    get_raw_job_by_id,
    load_candidate_profile_from_example,
    load_matching_profile_from_example,
)
from src.matchers.matcher import MatchJudgment, MatchResult, RejectedMatch, DimensionJudgment


def test_data_helpers_load_sample_data():
    job_offer = get_job_offer_by_id("2032767", "data/outputs/tanitjobs_structured_jobs.json")
    assert job_offer.job_id == "2032767"
    assert job_offer.title == "Stagiaire AI & Data Engineer - 100% remote"

    raw_job = get_raw_job_by_id("2032767", "data/outputs/tanitjobs_raw_job_list.json")
    assert raw_job.job_id == "2032767"
    assert raw_job.title == "Stagiaire AI & Data Engineer - 100% remote"

    candidate = load_candidate_profile_from_example()
    assert candidate.personal_information.full_name == "Yasmine Chakroun"

    matching = load_matching_profile_from_example()
    assert matching.education
    assert matching.skills


def test_match_and_rejection_records_include_inference_timestamp():
    result = MatchResult(
        job_url="https://example.com/jobs/123",
        candidate_id="cand-1",
        judgment=MatchJudgment(
            job_id="123",
            skills_fit=DimensionJudgment(score=1.0, explanation="Strong technical match"),
            experience_fit=DimensionJudgment(score=0.8, explanation="Good experience"),
            education_fit=DimensionJudgment(score=0.9, explanation="Relevant degree"),
            summary="Good fit overall.",
        ),
        overall_score=0.9,
        apply_priority=0.9,
    )
    rejected = RejectedMatch(
        job_url="https://example.com/jobs/456",
        candidate_id="cand-1",
        rejection_reason="Does not meet salary expectation",
    )

    assert result.inferred_at is not None
    assert rejected.inferred_at is not None
    assert result.model_dump(mode="json")["inferred_at"]
    assert rejected.model_dump(mode="json")["inferred_at"]
