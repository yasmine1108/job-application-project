from enum import Enum
from datetime import datetime

from pydantic import BaseModel, Field
import pytz

from src.shared import DEGREE_LEVEL_GUIDANCE, normalize_skill_name



class SkillCategory(str, Enum):
    PROGRAMMING_LANGUAGE = "programming_language"
    TECHNICAL = "technical"
    TOOL = "tool"
    SOFT = "soft"
    DOMAIN = "domain"
    OTHER = "other"


class ImportanceLevel(str, Enum):
    REQUIRED = "required"
    PREFERRED = "preferred"
    NICE_TO_HAVE = "nice_to_have"


class DegreeLevel(str, Enum):
    HIGH_SCHOOL = "high_school"
    SHORT_CYCLE = "short_cycle"
    ASSOCIATE = "associate"
    BACHELOR = "bachelor"
    MASTER = "master"
    DOCTORATE = "doctorate"
    OTHER = "other"


class JobSkillRequirement(BaseModel):
    name: str
    category: SkillCategory | None = None
    importance: ImportanceLevel = ImportanceLevel.REQUIRED
    min_years: int | None = None


class EducationRequirement(BaseModel):
    degree_level: DegreeLevel | None = Field(
        default=None,
        description="Minimum level required" + DEGREE_LEVEL_GUIDANCE,
    )
    raw_requirement: str | None = Field(
        default=None,
        description="The literal degree text from the posting, e.g. 'Bac+5 ou école d'ingénieur, master en data science'.",
    )
    years_of_study: int | None = Field(
        default=None,
        description="Total years of post-secondary study required (e.g. Licence=3, Diplôme d'Ingénieur=5, BAC+5=5).",
    )
    field_of_study: str | None = None
    importance: ImportanceLevel = ImportanceLevel.REQUIRED


class CertificationRequirement(BaseModel):
    name: str = Field(
        description=(
            "A professional certification ONLY — e.g. 'AWS Certified Solutions "
            "Architect', 'PMP', 'Scrum Master'. Do NOT include academic degrees "
            "here (Bachelor's, Master's, Diplôme d'Ingénieur, etc.) — those "
            "belong exclusively in required_education, never here."
        )
    )
    importance: ImportanceLevel = ImportanceLevel.REQUIRED


class LanguageRequirement(BaseModel):
    name: str = Field(description="A spoken/human language required, e.g. English, French. Never a programming language.")
    min_proficiency: str | None = Field(
        default=None,
        description="e.g. 'professional', 'fluent', 'native', 'conversational' — extracted from phrases like 'bon niveau', 'courant', 'niveau professionnel'.",
    )

class EmploymentType(str, Enum):
    FULL_TIME = "full-time"
    PART_TIME = "part-time"
    CONTRACT = "contract"
    INTERNSHIP = "internship"
    TEMPORARY = "temporary"
    VOLUNTEER = "volunteer"
    CDI = "CDI"
    OTHER = "other"


class WorkArrangement(str, Enum):
    REMOTE = "remote"
    HYBRID = "hybrid"
    ON_SITE = "on-site"


class JobStatus(str, Enum):
    OPEN = "open"
    CLOSED = "closed"

class RawJob(BaseModel):
    """No inference."""
    title: str | None = None
    company: str | None = None
    location: str | None = None
    description: str | None = None
    date_posted: str | None = None
    employment_type: str | None = None 
    raw_employment_type: str | None = None   
    work_arrangement: str | None = None  
    accepting_applications: bool = True
    expiration_date: str | None = None 
    job_url: str | None = None
    job_id: str | None = None
    easy_apply: bool = False
    scraped_at: datetime = Field(default_factory=lambda: datetime.now(pytz.UTC))

class JobOfferInference(BaseModel):
    """LLM output — matches JobOffer's inferred fields 1:1."""
    job_url:str | None = None
    location: str | None = None  # only meaningfully populated when the raw location was bad/missing
    skills: list[JobSkillRequirement] = Field(default_factory=list)
    required_experience: str | None = None
    min_years_experience: int | None = None
    required_languages: list[LanguageRequirement] = Field(default_factory=list)
    required_education: list[EducationRequirement] = Field(default_factory=list)
    required_certifications: list[CertificationRequirement] = Field(default_factory=list)
    description_language: str | None = None

class JobOfferInferenceBatch(BaseModel):
    results: list[JobOfferInference]

class JobOffer(BaseModel):
    """Matching profile — only fields a scoring/ranking step needs."""
    job_url: str
    job_id: str | None = None
    title : str | None = None
    description_language: str | None = None
    location: str | None = None

    employment_type: EmploymentType | None = None
    work_arrangement: WorkArrangement | None = None

    skills: list[JobSkillRequirement] = Field(default_factory=list)
    required_experience: str | None = None
    min_years_experience: int | None = None
    required_languages: list[LanguageRequirement] = Field(default_factory=list)
    required_education: list[EducationRequirement] = Field(default_factory=list)
    required_certifications: list[CertificationRequirement] = Field(default_factory=list)

    easy_apply: bool = False
    job_status: JobStatus = JobStatus.OPEN
    inferred_at: datetime = Field(default_factory=lambda: datetime.now(pytz.UTC))

    @classmethod
    def from_raw_and_inference(cls, raw_job: RawJob, job_inference: JobOfferInference) -> "JobOffer":
        return cls(
            job_url=raw_job.job_url,
            job_id=raw_job.job_id,
            title = raw_job.title,
            description_language=job_inference.description_language,
            location = raw_job.location,
            employment_type=EmploymentType(raw_job.employment_type) if raw_job.employment_type else None,
            work_arrangement=WorkArrangement(raw_job.work_arrangement) if raw_job.work_arrangement else None,
            skills=job_inference.skills,
            required_experience=job_inference.required_experience,
            min_years_experience=job_inference.min_years_experience,
            required_languages=job_inference.required_languages,
            required_education=job_inference.required_education,
            required_certifications=job_inference.required_certifications,
            easy_apply=raw_job.easy_apply,
        )

def normalize_job_skills(inference: JobOfferInference) -> JobOfferInference:
    for req in inference.skills:
        req.name = normalize_skill_name(req.name)
    return inference

