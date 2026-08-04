from src.data_helpers import (
    get_job_offer_by_id,
    get_raw_job_by_id,
    load_candidate_profile_from_example,
    load_matching_profile_from_example,
)


def test_data_helpers_load_sample_data():
    job_offer = get_job_offer_by_id("4429154944")
    assert job_offer.job_id == "4429154944"
    assert job_offer.title == "Software Engineer"

    raw_job = get_raw_job_by_id("4429154944")
    assert raw_job.job_id == "4429154944"
    assert raw_job.title == "Software Engineer"

    candidate = load_candidate_profile_from_example()
    assert candidate.personal_information.full_name == "Yasmine Chakroun"

    matching = load_matching_profile_from_example()
    assert matching.education
    assert matching.skills
