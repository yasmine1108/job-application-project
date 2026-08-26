from src.candidate_identity import ensure_candidate_id
from src.shared import normalize_skill_name, DEGREE_LEVEL_GUIDANCE
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
from pathlib import Path
from langchain_core.prompts import ChatPromptTemplate
import re
import phonenumbers


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
- Extract the candidate's location (city, and governorate/region if present) exactly as written near the name or contact details, e.g. 'Tunis, Tunisie'. If no location is stated anywhere in the CV, return null.
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
- ALWAYS attempt to fill "degree_level" and "years_of_study" for every entry, even when the CV doesn't state them explicitly - infer them from the degree name using the degree_level guidance below. Only leave them null if the degree name is too ambiguous to classify at all.
- If a field is missing, return null. Never invent information.
- Never return an empty list if any education information exists in the text below.

degree_level guidance: {degree_level_guidance}

Example:
Input table row: "Faculté des Sciences de Bizerte (FSB) | Sept. 2024 - Present | Diplome d'Ingenieur en Genie Logiciel | Bizerte, Tunisie"
Output entry: {{"degree": "Diplome d'Ingenieur en Genie Logiciel", "degree_level": "master", "years_of_study": 5, "institution": "Faculte des Sciences de Bizerte (FSB)", "field_of_study": "Genie Logiciel", "start_date": "Sept. 2024", "end_date": "Present", "description": null}}
Example 2:
Input: "Baccalauréat en Mathématiques – Mention Bien"
Output entry: {{"degree": "Baccalauréat", "degree_level": "high_school", "years_of_study": null, "institution": null, "field_of_study": "Mathématiques", "start_date": null, "end_date": null, "description": "Mention Bien"}}
Example 3:
Input: "Classe Préparatoire Intégrée (CPI) – Major de Promotion"
Output entry: {{"degree": "Classe Préparatoire Intégrée (CPI)", "degree_level": "short_cycle", "years_of_study": 2, "institution": null, "field_of_study": null, "start_date": null, "end_date": null, "description": "Major de Promotion"}}
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

A skill is a NAMED technology, tool, framework, language, methodology, or well-established competency
that would appear on a skills list or a job posting's requirements (e.g. "Python", "Docker", "Machine Learning",
"Agile", "communication", "software testing").

A skill is NOT a paraphrased action or responsibility clause lifted from a bullet point
(e.g. do NOT extract things like "publishing content", "managing relationships", "job applications",
"data cleaning steps" as skills just because they appear in a sentence describing what someone did -
only extract the actual named technology/methodology terms from within that sentence, if any).

Rules:
- Skills are often listed as a comma-separated list under a category header (e.g. "Langages: Python, Java, SQL").
- Split each comma-separated item into its OWN separate Skill object. Do not group multiple skills into one object.
- Use the category header from the dedicated skills section (e.g. "Langages", "Cloud, DevOps & MLOps") as the "category" field for each skill under it.
- Also extract named technologies/tools mentioned in experience/project bullet points (e.g. "LangChain", "ChromaDB", "Scikit-Learn") even if not in the main skills section - but do NOT convert the surrounding sentence's action/verb phrasing into a skill.
- Also extract named technologies/tools/methodologies mentioned in experience, project, AND education entries (e.g. relevant coursework like "AWS Academy Data Engineering", "OpenMP", "MPI") - not just from the main skills section.
- category field: TECHNICAL = frameworks, libraries, databases, cloud/DevOps platforms, ML/data concepts, e.g. React, PostgreSQL, Docker, AWS, Machine Learning. TOOL = standalone software utilities, e.g. Git, Selenium, EVE-NG. If genuinely unsure between TECHNICAL and TOOL, prefer TECHNICAL.
- Never return an empty list if any skills are present in the text below.
- Never invent skills that are not written in the text.
- "evidence" should be null unless the CV text explicitly ties that skill to a specific bullet point elsewhere.

Example (correct):
Input: "Langages : Python, Java, SQL"
Output skills: [
  {{"name": "Python", "category": "programming_language", "evidence": null}},
  {{"name": "Java", "category": "programming_language", "evidence": null}},
  {{"name": "SQL", "category": "programming_language", "evidence": null}}
]

Example (what NOT to do):
Input: "Développement Full-Stack : Conception d'une plateforme inspirée de LinkedIn permettant la publication de contenus, la gestion des relations professionnelles et la candidature à des offres d'emploi."
WRONG - do not extract: "publication de contenus", "gestion des relations professionnelles", "candidature à des offres d'emploi" (these are just a description of what the platform does, not skills)
CORRECT - nothing to extract here unless a named technology appears elsewhere in that entry (e.g. "Node.js", "Express", "MongoDB" from the technologies list).
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
            markdown=document.content, tables=tables_text, degree_level_guidance=DEGREE_LEVEL_GUIDANCE
        )
        self._debug_dump("education", education_messages)
        education_result: EducationList = (
            self.education_prompt | self.education_llm
        ).invoke({"markdown": document.content, "tables": tables_text, "degree_level_guidance": DEGREE_LEVEL_GUIDANCE})

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
        candidate_profile = populate_skill_evidence(candidate_profile)
        candidate_profile = normalize_profile_skills(candidate_profile)
        candidate_profile = enforce_standard_years_of_study(candidate_profile)
        candidate_profile.personal_information.country_code = extract_phone_country_code(candidate_profile.personal_information.phone)
        # Cache the extracted profile
        cache_dir = Path("data/outputs")
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_filename = f"{Path(str(document.file_name)).stem}_profile.json"
        cache_path = cache_dir / cache_filename

        candidate_profile = ensure_candidate_id(candidate_profile, cache_path)
        
        with open(cache_path, "w", encoding="utf-8") as f:
            f.write(candidate_profile.model_dump_json(indent=2))
        
        return candidate_profile


def extract_phone_country_code(phone: str | None) -> str | None:
    """Returns ISO 3166-1 alpha-2 (e.g. 'TN') only when the phone string
    itself contains an explicit country calling code (+216..., 00216...).
    Returns None otherwise — do not guess from a bare local number."""
    if not phone or not phone.strip():
        return None
    cleaned_phone = phone.strip()

    # Convert leading IDD prefix "00" to "+" standard E.164 notation
    if cleaned_phone.startswith("00"):
        cleaned_phone = "+" + cleaned_phone[2:]
    try:
        parsed = phonenumbers.parse(cleaned_phone, None)  # region=None forces explicit-code-only parsing
        if phonenumbers.is_valid_number(parsed):
            return phonenumbers.region_code_for_number(parsed)
    except phonenumbers.NumberParseException:
        pass
    return None

STANDARD_YEARS_BY_DEGREE_LEVEL = {
    "high_school": None,
    "short_cycle": 2,
    "associate": 2,
    "bachelor": 3,
    "master": 5,
    "doctorate": 8,
    "other": None,
}

def enforce_standard_years_of_study(profile: CandidateProfile) -> CandidateProfile:
    """
    The LLM tends to compute years_of_study from the entry's start/end dates
    (e.g. an in-progress degree spanning 2024-2027 -> 3) instead of the
    degree's actual total duration (Diplome d'Ingenieur = 5 years total,
    regardless of how many years remain). Standard duration by degree_level
    is well-defined and not something that needs LLM judgment, so we
    override it deterministically here rather than relying on prompting.
    """
    for edu in profile.education:
        if edu.degree_level:
            standard = STANDARD_YEARS_BY_DEGREE_LEVEL.get(edu.degree_level.value)
            if standard is not None:
                edu.years_of_study = standard
    return profile

def normalize_profile_skills(profile: CandidateProfile) -> CandidateProfile:
    for skill in profile.skills:
        skill.name = normalize_skill_name(skill.name)
    return profile

def populate_skill_evidence(profile: CandidateProfile) -> CandidateProfile:
    """
    For each skill, scan experience/project text for mentions and attach
    the matching source lines as evidence. Runs after LLM extraction,
    no inference involved — pure string matching against the candidate's
    own stated history.
    """
    for skill in profile.skills:
        evidence = _find_evidence_for_skill(skill.name, profile)
        skill.evidence = evidence if evidence else None
    return profile


def _find_evidence_for_skill(skill_name: str, profile: CandidateProfile) -> list[str]:
    pattern = re.compile(rf"\b{re.escape(skill_name)}\b", re.IGNORECASE)
    evidence = []

    for exp in profile.experience:
        if any(t.lower() == skill_name.lower() for t in exp.technologies):
            label = f"{exp.job_title} at {exp.company}" if exp.job_title and exp.company else (exp.job_title or exp.company or "Experience")
            evidence.append(f"Used in role: {label}")

        # description / responsibilities — text mentions
        texts_to_scan = ([exp.description] if exp.description else []) + exp.responsibilities
        for text in texts_to_scan:
            if text and pattern.search(text):
                snippet = _extract_snippet(text, pattern)
                evidence.append(snippet)

    for proj in profile.projects:
        if any(t.lower() == skill_name.lower() for t in proj.technologies):
            evidence.append(f"Used in project: {proj.title}" if proj.title else "Used in a project")

        texts_to_scan = ([proj.summary] if proj.summary else []) + proj.highlights
        for text in texts_to_scan:
            if text and pattern.search(text):
                snippet = _extract_snippet(text, pattern)
                evidence.append(snippet)

    # dedupe while preserving order
    seen = set()
    deduped = []
    for e in evidence:
        if e not in seen:
            seen.add(e)
            deduped.append(e)
    return deduped


def _extract_snippet(text: str, pattern: re.Pattern, context_chars: int = 60) -> str:
    """Return a short window of text around the first match, not the whole
    paragraph. Boundaries are pulled back to the nearest whitespace so words
    aren't sliced in half."""
    match = pattern.search(text)
    if not match:
        return text

    start = max(0, match.start() - context_chars)
    if start > 0:
        next_space = text.find(" ", start)
        if 0 <= next_space < match.start():
            start = next_space + 1

    end = min(len(text), match.end() + context_chars)
    if end < len(text):
        prev_space = text.rfind(" ", match.end(), end)
        if prev_space > match.end():
            end = prev_space

    snippet = text[start:end].strip()
    if start > 0:
        snippet = "…" + snippet
    if end < len(text):
        snippet = snippet + "…"
    return snippet