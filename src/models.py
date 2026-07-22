from dataclasses import dataclass

from pydantic import BaseModel

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
    category: str | None
    evidence: list[str] | None

class Certification(BaseModel):
    name: str
    issuer: str | None
    date: str | None

class Language(BaseModel):
    name: str
    proficiency: str | None

class JobOffer(BaseModel):
    title: str | None
    company: str | None
    location: str | None
    description: str | None
    date_posted: str | None
    job_url: str | None
    accepting_applications: bool = True
    employment_type: str | None # e.g., "Full-time", "Part-time", "Contract", "Internship"
    work_arrangement: str | None # e.g., "Remote", "On-site", "Hybrid"
    required_skills: list[str] = []
    required_experience: str | None # e.g., "2-5 years", "Entry-level", "Senior"
    easy_apply: bool = False

class MatchingProfile(BaseModel):
    professional_summary: str | None
    education: list[Education] = []
    experience: list[Experience] = []
    projects: list[Project] = []
    skills: list[Skill] = []
    certifications: list[Certification] = []
    # languages: list[Language] = []

class CandidateProfile(BaseModel):
    personal_information: PersonalInformation
    professional_summary: str | None
    education: list[Education] = []
    experience: list[Experience] = []
    skills: list[Skill] = []
    projects: list[Project] = []
    certifications: list[Certification] = []
    # languages: list[Language] = []

    def get_matching_profile(self):
        return MatchingProfile(
            professional_summary=self.professional_summary,
            education=self.education,
            experience=self.experience,
            projects=self.projects,
            skills=self.skills,
            certifications=self.certifications,
            # languages=self.languages
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