from datetime import datetime
from enum import Enum
from pydantic import BaseModel, Field
import pytz

class EmploymentType(str, Enum):
    FULL_TIME = "full-time"
    PART_TIME = "part-time"
    CONTRACT = "contract"
    INTERNSHIP = "internship"
    TEMPORARY = "temporary"
    VOLUNTEER = "volunteer"
    OTHER = "other"


class WorkArrangement(str, Enum):
    REMOTE = "remote"
    HYBRID = "hybrid"
    ON_SITE = "on-site"


class ApplicationStatus(str, Enum):
    NOT_APPLIED = "not_applied"
    APPLIED = "applied"
    FAILED = "failed"
    SKIPPED = "skipped"
    CLOSED = "closed"

class RawJob(BaseModel):
    """No inference."""
    title: str | None = None
    company: str | None = None
    location: str | None = None
    description: str | None = None
    date_posted: str | None = None
    employment_type: str | None = None   
    work_arrangement: str | None = None  
    accepting_applications: bool = True
    job_url: str | None = None
    job_id: str | None = None
    easy_apply: bool = False
    scraped_at: datetime = Field(default_factory=lambda: datetime.now(pytz.UTC))

class JobOfferInference(BaseModel):
    required_skills: list[str] = Field(default_factory=list)
    preferred_skills: list[str] = Field(default_factory=list)
    required_experience: str | None = None
    min_years_experience: int | None = None
    required_languages: list[str] = Field(default_factory=list)
    required_education: list[str] = Field(default_factory=list)
    required_certifications: list[str] = Field(default_factory=list)
    required_soft_skills: list[str] = Field(default_factory=list)
    description_language: str | None = None

class JobOffer(BaseModel):
    """Matching profile — only fields a scoring/ranking step needs."""
    job_url: str                 
    job_id: str | None = None
    description_language: str | None = None #the language of the cv that will be sent should match the language of the job description

    employment_type: EmploymentType | None = None
    work_arrangement: WorkArrangement | None = None
    required_skills: list[str] = Field(default_factory=list)
    required_experience: str | None = None
    min_years_experience: int | None = None
    preferred_skills: list[str] = Field(default_factory=list)
    required_certifications: list[str] = Field(default_factory=list)
    required_soft_skills: list[str] = Field(default_factory=list)
    required_education: list[str] = Field(default_factory=list)

    easy_apply: bool = False

    application_status: ApplicationStatus = ApplicationStatus.NOT_APPLIED
    applied_at: datetime | None = None

    inferred_at: datetime = Field(default_factory=lambda: datetime.now(pytz.UTC))


    def get_job_offer(self, raw_job:RawJob, job_inference:JobOfferInference):
        return JobOffer(
            job_url=raw_job.job_url,
            job_id=raw_job.job_id,
            description_language=job_inference.description_language,
            employment_type=EmploymentType(raw_job.employment_type) if raw_job.employment_type else None,
            work_arrangement=WorkArrangement(raw_job.work_arrangement) if raw_job.work_arrangement else None,
            required_skills=job_inference.required_skills,
            required_experience=job_inference.required_experience,
            min_years_experience=job_inference.min_years_experience,
            preferred_skills=job_inference.preferred_skills,
            required_certifications=job_inference.required_certifications,
            required_soft_skills=job_inference.required_soft_skills,
            required_education=job_inference.required_education,
            easy_apply=raw_job.easy_apply
        )