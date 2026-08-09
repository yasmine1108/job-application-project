from dataclasses import dataclass

from pydantic import BaseModel, Field

from src.shared import DEGREE_LEVEL_GUIDANCE
from src.models_job import DegreeLevel, SkillCategory

@dataclass
class ParsedTable:
    page: int
    rows: list[list[str]]

@dataclass
class ParsedDocument:
    file_name: str
    file_type: str
    content: str
    links: list[str]
    tables : list[ParsedTable]


class PersonalInformation(BaseModel):
    full_name: str | None
    email: str | None
    phone: str | None
    linkedin: str | None
    github: str | None

class Education(BaseModel):
    degree: str | None
    degree_level: DegreeLevel | None = Field(
        default=None,
        description=DEGREE_LEVEL_GUIDANCE,
    )
    years_of_study: int | None = Field(
        default=None,
        description="Total years of post-secondary study to obtain this degree (e.g. Licence=3, Diplôme d'Ingénieur=5, BAC+5=5).",
    )
    institution: str | None
    field_of_study: str | None
    start_date: str | None
    end_date: str | None
    description: str | None

class Experience(BaseModel):
    job_title: str | None
    company: str | None
    domain: str | None
    location: str | None
    employment_type: str | None
    start_date: str | None
    end_date: str | None
    duration_months: int | None
    description: str | None
    responsibilities: list[str]
    technologies: list[str]


class Project(BaseModel):
    title: str | None
    summary: str | None
    highlights: list[str]
    technologies: list[str]
    github: str | None

class Skill(BaseModel):
    name: str
    category: SkillCategory | None = Field(
        default=None,
        description=(
            "Category of the skill:\n"
            "- PROGRAMMING_LANGUAGE: coding/query languages only, e.g. Python, Java, SQL, JavaScript, C++.\n"
            "- TECHNICAL: frameworks, libraries, databases, cloud/DevOps platforms, data engineering tools, "
            "e.g. React, Node.js, PostgreSQL, MongoDB, Docker, Kubernetes, AWS, Hadoop.\n"
            "- TOOL: standalone software/utilities used in the work, e.g. Git, GitHub, Selenium, EVE-NG, pfSense.\n"
            "- SOFT: interpersonal/non-technical skills, e.g. communication, leadership, teamwork.\n"
            "- DOMAIN: subject-matter/business domain knowledge, e.g. insurance, fintech, healthcare, IoT.\n"
            "- OTHER: anything technical that doesn't fit above.\n"
            "Do NOT put spoken/human languages (French, English, Arabic) here — those belong in spoken_languages."
        ),
    )
    evidence: list[str] | None

class Certification(BaseModel):
    name: str
    issuer: str | None
    date: str | None

class SpokenLanguage(BaseModel):
    name: str = Field(description="A human/spoken language, e.g. French, English, Arabic. Never a programming language.")
    proficiency: str | None

class MatchingProfile(BaseModel):
    professional_summary: str | None
    education: list[Education] = Field(default_factory=list)
    experience: list[Experience] = Field(default_factory=list)
    projects: list[Project] = Field(default_factory=list)
    skills: list[Skill] = Field(default_factory=list)
    certifications: list[Certification] = Field(default_factory=list)
    spoken_languages: list[SpokenLanguage] = Field(default_factory=list)

class CandidateProfile(BaseModel):
    personal_information: PersonalInformation
    professional_summary: str | None
    education: list[Education] = Field(default_factory=list)
    experience: list[Experience] = Field(default_factory=list)
    skills: list[Skill] = Field(default_factory=list)
    projects: list[Project] = Field(default_factory=list)
    certifications: list[Certification] = Field(default_factory=list)
    spoken_languages: list[SpokenLanguage] = Field(default_factory=list)

    def get_matching_profile(self):
        return MatchingProfile(
            professional_summary=self.professional_summary,
            education=self.education,
            experience=self.experience,
            projects=self.projects,
            skills=self.skills,
            certifications=self.certifications,
            spoken_languages=self.spoken_languages
        )


# --- Wrapper models used for split extraction calls ---
# with_structured_output needs a single Pydantic model as its target,
# so list-returning calls get wrapped in a small container model.

class PersonalInfoAndSummary(BaseModel):
    personal_information: PersonalInformation
    professional_summary: str | None

class EducationList(BaseModel):
    education: list[Education]

class ExperienceList(BaseModel):
    experience: list[Experience]

class ProjectList(BaseModel):
    projects: list[Project]

class SkillList(BaseModel):
    skills: list[Skill]

class CertificationList(BaseModel):
    certifications: list[Certification]

class SpokenLanguageList(BaseModel):
    spoken_languages: list[SpokenLanguage]