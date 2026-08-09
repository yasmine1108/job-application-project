from agent_project.src.matchers.matcher import CandidatePreferences, apply_hard_filters
from src.models import SpokenLanguage
from src.models_job import ApplicationStatus, EmploymentType, JobOffer, WorkArrangement


def test_relocate_false_rejects_on_site_job_in_other_country():
    job = JobOffer(
        job_url="https://example.com/job/1",
        title="Software Engineer",
        employment_type=EmploymentType.FULL_TIME,
        work_arrangement=WorkArrangement.ON_SITE,
        location="Berlin, Berlin, Germany",
        application_status=ApplicationStatus.NOT_APPLIED,
        required_languages=[],
    )

    preferences = CandidatePreferences(
        country="Tunisia",
        willing_to_relocate=False,
    )

    reason = apply_hard_filters(job, [SpokenLanguage(name="English", proficiency="professional")], preferences)

    assert reason == "On-site job in Germany, candidate not willing to relocate"


def test_distance_limit_rejects_far_on_site_job():
    job = JobOffer(
        job_url="https://example.com/job/2",
        title="Data Engineer",
        employment_type=EmploymentType.FULL_TIME,
        work_arrangement=WorkArrangement.ON_SITE,
        location="Sfax, Sfax, Tunisia",
        application_status=ApplicationStatus.NOT_APPLIED,
        required_languages=[],
    )

    preferences = CandidatePreferences(
        country="Tunisia",
        governorate="Tunis",
        max_commute_distance_km=100,
        willing_to_relocate=False,
    )

    reason = apply_hard_filters(job, [SpokenLanguage(name="English", proficiency="professional")], preferences)

    assert reason is not None
    assert reason.startswith("On-site job ")
    assert "exceeds max commute of 100" in reason
