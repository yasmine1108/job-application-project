from src.models import (
    CandidateProfile,
    ParsedDocument,
    PersonalInfoAndSummary,
    EducationList,
    ExperienceList,
    ProjectList,
    SkillList,
    CertificationList,
    SpokenLanguageList,
)
import json
from pathlib import Path
from langchain_core.prompts import ChatPromptTemplate


class CVExtractor:

    def __init__(self, llm, debug=False):
        self.raw_llm = llm
        self.debug = debug

        # One structured-output-bound llm per section, so each call
        # only has to satisfy a small, focused schema instead of the
        # entire CandidateProfile at once.
        self.personal_llm = llm.with_structured_output(PersonalInfoAndSummary)
        self.education_llm = llm.with_structured_output(EducationList)
        self.experience_llm = llm.with_structured_output(ExperienceList)
        self.project_llm = llm.with_structured_output(ProjectList)
        self.skill_llm = llm.with_structured_output(SkillList)
        self.certification_llm = llm.with_structured_output(CertificationList)
        self.spoken_languages_llm = llm.with_structured_output(SpokenLanguageList)

        self.personal_prompt = ChatPromptTemplate.from_messages([
            ("system", """
You are an expert CV information extraction system.

Extract ONLY the candidate's personal information and professional summary.

Rules:
- Return only information contained in the CV.
- Never invent information.
- If a field is missing, return null.
- Use the detected hyperlinks to identify LinkedIn, GitHub, portfolio or personal websites.
- The professional summary should preserve the candidate's own wording/intent, not a generic paraphrase.
- Only extract a professional_summary if the CV contains an explicit short profile/summary/objective statement (often near the top, under the name/title). 
- Do NOT synthesize, compile, or write a new summary from scattered information found elsewhere in the CV (skills, experience, projects).
- If no such explicit statement exists, return null.
- If a short subtitle/tagline exists near the name (e.g. a field of study + job-seeking intent), 
  extract it as-is or near-verbatim - do not expand it into a longer paragraph.
            """),
            ("human", """
CV Markdown:

{markdown}

Detected hyperlinks:

{links}
            """),
        ])

        self.education_prompt = ChatPromptTemplate.from_messages([
            ("system", """
You are an expert at extracting education history from CVs.

Your ONLY task is to extract every education entry (degree, diploma, certificate program, high school, etc).

Rules:
- Extract EVERY row/entry found, even if the CV only has one.
- Each entry becomes one separate object in the "education" list. Never merge two entries into one.
- If the source is a table, each table row (after the header) is normally one education entry.
- Institution, degree/diploma title, dates and location may be split across multiple table cells or lines - combine them correctly into a single entry.
- Normalize dates to a consistent format when possible (e.g. "Sept. 2024 - Present").
- If a field is missing, return null. Never invent information.
- Never return an empty list if any education information exists in the text below.

Example:
Input table row: "Faculté des Sciences de Bizerte (FSB) | Sept. 2024 - Present | Diplome d'Ingenieur en Genie Logiciel | Bizerte, Tunisie"
Output entry: {{"degree": "Diplome d'Ingenieur en Genie Logiciel", "institution": "Faculte des Sciences de Bizerte (FSB)", "field_of_study": "Genie Logiciel", "start_date": "Sept. 2024", "end_date": "Present", "description": null}}
Example 2:
Input: "Baccalauréat en Mathématiques – Mention Bien"
Output entry: {{"degree": "Baccalauréat", "institution": null, "field_of_study": "Mathématiques", "start_date": null, "end_date": null, "description": "Mention Bien"}}
            """),
            ("human", """
CV Markdown (look for an Education / Formation / Diplomes section):

{markdown}

Detected tables (if present, treat as the authoritative source for education data - the markdown above may render the same table with broken formatting):

{tables}
            """),
        ])

        self.experience_prompt = ChatPromptTemplate.from_messages([
            ("system", """
You are an expert at extracting professional experience from CVs.

Your ONLY task is to extract every work experience / internship entry.

Rules:
- Extract EVERY bullet point under each role into the "responsibilities" list. Never summarize or omit any.
- Keep technologies exactly as written, in the "technologies" list.
- Descriptions should preserve all technical details.
- If a field is missing, return null. Never invent information.
- Only extract REAL professional experience: paid jobs, internships (stages), or freelance work at a company/organization.
- Do NOT include entries from an "Academic Projects" / "Projets Académiques" / "Projets Personnels" section 
- those are handled separately and must be excluded here entirely, even if they resemble structured entries.
- A red flag that an entry does NOT belong here: the "company" would be a school/university and the entry describes a class project rather than an employment relationship.
            """),
            ("human", """
CV Markdown (look for Experience / Experience Professionnelle sections):

{markdown}
            """),
        ])

        self.project_prompt = ChatPromptTemplate.from_messages([
            ("system", """
You are an expert at extracting academic/personal projects from CVs.

Your ONLY task is to extract every project entry.

Rules:
- Extract EVERY bullet point under each project into the "highlights" list. Never summarize or omit any.
- Keep technologies exactly as written, in the "technologies" list.
- Use detected hyperlinks to fill "github" when a project links to a repository.
- If a field is missing, return null. Never invent information.
- Only extract entries from an Academic/Personal Projects section (e.g. "Projets Académiques", "Personal Projects").
- Do NOT include real professional work experience or internships - those are handled separately.
            """),
            ("human", """
CV Markdown (look for Projects / Projets Academiques sections):

{markdown}

Detected hyperlinks:

{links}
            """),
        ])

        self.skill_prompt = ChatPromptTemplate.from_messages([
            ("system", """
You are an expert at extracting technical/soft skills from CVs.

Your ONLY task is to extract every individual skill as a SEPARATE object in the "skills" list.

Rules:
- Skills are often listed as a comma-separated list under a category header (e.g. "Langages: Python, Java, SQL").
- Split each comma-separated item into its OWN separate Skill object. Do not group multiple skills into one object.
- Use the category header (e.g. "Langages", "Cloud, DevOps & MLOps") as the "category" field for each skill under it.
- Extract EVERY skill mentioned anywhere in the CV, not just from a dedicated skills section - also check technologies mentioned in experience/project entries.
- Never return an empty list if any skills are present in the text below.
- Never invent skills that are not written in the text.
- "evidence" should be null unless the CV text explicitly ties that skill to a specific bullet point elsewhere.

Example:
Input: "Langages : Python, Java, SQL"
Output skills: [
  {{"name": "Python", "category": "Langages", "evidence": null}},
  {{"name": "Java", "category": "Langages", "evidence": null}},
  {{"name": "SQL", "category": "Langages", "evidence": null}}
]
            """),
            ("human", """
CV Markdown (look for Skills / Competences Techniques sections, and technologies mentioned elsewhere):

{markdown}
            """),
        ])

        self.certification_prompt = ChatPromptTemplate.from_messages([
            ("system", """
You are an expert at extracting certifications from CVs.

Your ONLY task is to extract every certification entry.

Rules:
- If a field is missing, return null. Never invent information.
- If there are no certifications in the CV, return an empty list.
            """),
            ("human", """
CV Markdown (look for Certifications section):

{markdown}
            """),
        ])

        self.spoken_languages_prompt = ChatPromptTemplate.from_messages([
            ("system", """
You are an expert at extracting spoken languages from CVs.

Your ONLY task is to extract every human/spoken language mentioned in the CV.

Rules:
- Extract only human languages such as English, French, Arabic, Spanish, etc.
- Do NOT extract programming languages or technical skills.
- If a field is missing, return null. Never invent information.
- If there are no spoken languages in the CV, return an empty list.
- Preserve the language names as written in the CV when possible.
            """),
            ("human", """
CV Markdown (look for Languages / Langues / Spoken Languages sections, and any mention in the profile or personal info):

{markdown}
            """),
        ])

    def table_to_text(self, tables):
        text = ""
        for table in tables:
            text += "\nDetected table:\n"
            for i, row in enumerate(table.rows):
                text += f"\nRow {i+1}:\n"
                for j, cell in enumerate(row):
                    if cell:
                        text += f"- Column {j+1}: {cell.strip()}\n"
        return text

    def _debug_dump(self, name, messages):
        if not self.debug:
            return
        with open(f"debug_{name}.txt", "w", encoding="utf-8") as f:
            for msg in messages:
                f.write(f"\n\n===== {msg.type.upper()} =====\n\n")
                f.write(msg.content)

    def extract(self, document: ParsedDocument) -> CandidateProfile:
        tables_text = self.table_to_text(document.tables)

        # Personal info + summary
        personal_messages = self.personal_prompt.format_messages(
            markdown=document.content, links=document.links
        )
        self._debug_dump("personal", personal_messages)
        personal_result: PersonalInfoAndSummary = (
            self.personal_prompt | self.personal_llm
        ).invoke({"markdown": document.content, "links": document.links})

        # Education
        education_messages = self.education_prompt.format_messages(
            markdown=document.content, tables=tables_text
        )
        self._debug_dump("education", education_messages)
        education_result: EducationList = (
            self.education_prompt | self.education_llm
        ).invoke({"markdown": document.content, "tables": tables_text})

        # Experience
        experience_messages = self.experience_prompt.format_messages(
            markdown=document.content
        )
        self._debug_dump("experience", experience_messages)
        experience_result: ExperienceList = (
            self.experience_prompt | self.experience_llm
        ).invoke({"markdown": document.content})

        # Projects
        project_messages = self.project_prompt.format_messages(
            markdown=document.content, links=document.links
        )
        self._debug_dump("projects", project_messages)
        project_result: ProjectList = (
            self.project_prompt | self.project_llm
        ).invoke({"markdown": document.content, "links": document.links})

        # Skills
        skill_messages = self.skill_prompt.format_messages(markdown=document.content)
        self._debug_dump("skills", skill_messages)
        skill_result: SkillList = (
            self.skill_prompt | self.skill_llm
        ).invoke({"markdown": document.content})

        # Certifications
        certification_messages = self.certification_prompt.format_messages(
            markdown=document.content
        )
        self._debug_dump("certifications", certification_messages)
        certification_result: CertificationList = (
            self.certification_prompt | self.certification_llm
        ).invoke({"markdown": document.content})

        # Spoken languages
        spoken_languages_messages = self.spoken_languages_prompt.format_messages(
            markdown=document.content
        )
        self._debug_dump("spoken_languages", spoken_languages_messages)
        spoken_languages_result: SpokenLanguageList = (
            self.spoken_languages_prompt | self.spoken_languages_llm
        ).invoke({"markdown": document.content})

        candidate_profile = CandidateProfile(
            personal_information=personal_result.personal_information,
            professional_summary=personal_result.professional_summary,
            education=education_result.education,
            experience=experience_result.experience,
            projects=project_result.projects,
            skills=skill_result.skills,
            certifications=certification_result.certifications,
            spoken_languages=spoken_languages_result.spoken_languages,
        )

        # Cache the extracted profile
        cache_dir = Path("data/outputs")
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_filename = f"{Path(str(document.file_name)).stem}_profile.json"
        cache_path = cache_dir / cache_filename
        
        with open(cache_path, "w", encoding="utf-8") as f:
            f.write(candidate_profile.model_dump_json(indent=2))
        
        return candidate_profile
