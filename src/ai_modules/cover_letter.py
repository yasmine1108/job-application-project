"""
Cover letter generation.

Generates a tailored cover letter, in the job posting's own language, from:
- CandidateProfile: the concrete facts (skills, experience, education) the
  letter is allowed to cite.
- MatchResult: overall_score (already weighted, used as-is) plus its nested
  MatchJudgment for the per-dimension explanations, so the letter
  foregrounds the right things instead of restating the whole CV.
- JobOffer (structured, primary source) + optional raw description
  (secondary, tone/culture only), so the letter reads as written for
  *this* posting, in job_offer.description_language ("fr" or "en").

Uses FallbackLLM.generate_structured (src.llm.fallback), matching how
Matcher itself calls the LLM.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from config.settings import Settings
from src.models import CandidateProfile
from src.models_job import JobOffer
from src.matchers.matcher import MatchResult
from src.llm.fallback import FallbackLLM


class CoverLetterDraft(BaseModel):
    letter: str = Field(
        description=(
            "Full cover letter text, in the language specified by the system "
            "prompt, ready to submit as-is. No placeholders, no brackets, "
            "no meta-commentary."
        )
    )

COVER_LETTER_BASE_RULES = """Tu rediges des lettres de motivation pour des candidatures a des offres d'emploi ou de stage.

Regles strictes :
- N'affirme QUE des faits presents dans le profil du candidat fourni. N'invente jamais une experience, une duree, une competence ou un diplome.
- Reste concis : 2 a 3 paragraphes courts, pas de formules toutes faites repetees.
- Cite 2 a 3 elements concrets et verifiables (technologie, projet, formation) qui font le lien explicite avec l'offre, en priorite ceux identifies dans l'analyse d'adequation fournie.
- Adapte le ton au niveau du poste (stage, junior, etc.) sans exagerer le niveau d'experience du candidat.
- Ne mets aucun placeholder, aucune balise, aucun commentaire hors du texte de la lettre.
- Termine par une formule de politesse standard suivie du nom complet du candidat. Ce nom DOIT etre copie exactement depuis le profil du candidat fourni ("Nom complet du candidat") -- ne l'invente jamais et ne le deduis jamais d'ailleurs.
"""

# JobOffer.description_language is always an ISO code: "fr" or "en".
LANGUAGE_NAMES = {
    "fr": "francais",
    "en": "anglais",
}
DEFAULT_LETTER_LANGUAGE_CODE = "fr"


def _language_instruction(description_language: str | None) -> str:
    code = (description_language or DEFAULT_LETTER_LANGUAGE_CODE).strip().lower()
    language = LANGUAGE_NAMES.get(code, LANGUAGE_NAMES[DEFAULT_LETTER_LANGUAGE_CODE])
    return f"Redige la lettre de motivation entierement en {language}, y compris les formules de politesse."


def build_cover_letter_system_prompt(description_language: str | None) -> str:
    return COVER_LETTER_BASE_RULES + "\n" + _language_instruction(description_language)


def _format_candidate_facts(candidate: CandidateProfile) -> str:
    """Flatten the parts of the profile the letter is allowed to cite."""
    lines: list[str] = []
    full_name = candidate.personal_information.full_name
    if full_name:
            lines.append(f"Nom complet du candidat (a utiliser tel quel dans la signature): {full_name}")
    if candidate.professional_summary:
        lines.append(f"Resume professionnel: {candidate.professional_summary}")

    for edu in candidate.education:
        lines.append(
            f"Formation: {edu.degree or ''} en {edu.field_of_study or ''} "
            f"- {edu.institution or ''} ({edu.start_date or '?'} - {edu.end_date or '?'})"
        )

    for exp in candidate.experience:
        techs = ", ".join(exp.technologies) if exp.technologies else ""
        lines.append(
            f"Experience: {exp.job_title or ''} chez {exp.company or ''} "
            f"({exp.start_date or '?'} - {exp.end_date or '?'}). "
            f"Technologies: {techs}."
        )

    for proj in candidate.projects:
        techs = ", ".join(proj.technologies) if proj.technologies else ""
        lines.append(f"Projet: {proj.title or ''} - {proj.summary or ''}. Technologies: {techs}.")

    skill_names = [s.name for s in candidate.skills]
    if skill_names:
        lines.append("Competences: " + ", ".join(skill_names))

    return "\n".join(lines)


def _format_match_reasoning(match_result: MatchResult) -> str:
    """Surface *why* the match is strong, so the letter foregrounds the right facts."""
    judgment = match_result.judgment
    return (
        f"Adequation competences (score {judgment.skills_fit.score}): {judgment.skills_fit.explanation}\n"
        f"Adequation experience (score {judgment.experience_fit.score}): {judgment.experience_fit.explanation}\n"
        f"Adequation formation (score {judgment.education_fit.score}): {judgment.education_fit.explanation}\n"
        f"Synthese: {judgment.summary}"
    )


def _format_job_facts(job_offer: JobOffer, company: str) -> str:
    """
    Structured job facts -- the primary source for what the letter can
    reference about the role. Precise and already normalized by the
    extraction pipeline, unlike free-text description.
    """
    lines = [f"Poste: {job_offer.title or ''} chez {company}"]

    if job_offer.required_experience or job_offer.min_years_experience:
        lines.append(
            f"Experience requise: {job_offer.required_experience or ''} "
            f"({job_offer.min_years_experience or '?'} ans min.)"
        )

    if job_offer.skills:
        skill_bits = [
            f"{s.name} ({s.importance.value})" for s in job_offer.skills
        ]
        lines.append("Competences recherchees: " + ", ".join(skill_bits))

    if job_offer.required_education:
        for edu_req in job_offer.required_education:
            lines.append(
                f"Formation requise: {edu_req.raw_requirement or edu_req.degree_level or ''} "
                f"({edu_req.importance.value})"
            )

    if job_offer.required_certifications:
        cert_names = [c.name for c in job_offer.required_certifications]
        lines.append("Certifications recherchees: " + ", ".join(cert_names))

    return "\n".join(lines)


def build_cover_letter_prompt(
    candidate: CandidateProfile,
    match_result: MatchResult,
    job_offer: JobOffer,
    company: str,
    job_description: str | None = None,
) -> str:
    parts = [
        "Offre visee (donnees structurees -- source principale des faits sur le poste) :\n"
        + _format_job_facts(job_offer, company)
    ]
    if job_description:
        # Secondary, optional signal: only for tone/culture nuance a flattened
        # skill list loses (see matcher.py's own rationale for raw text).
        # Not the source of factual claims about the role.
        parts.append(
            "Extrait de la description brute de l'offre (usage: contexte/ton uniquement, "
            "ne pas citer verbatim) :\n" + job_description[:1500]
        )
    parts.append("Profil du candidat (seuls ces faits peuvent etre cites) :\n" + _format_candidate_facts(candidate))
    parts.append("Analyse d'adequation avec l'offre :\n" + _format_match_reasoning(match_result))
    parts.append("Redige la lettre de motivation en respectant les regles du system prompt.")
    return "\n\n".join(parts)


def generate_cover_letter(
    candidate: CandidateProfile,
    match_result: MatchResult,
    job_offer: JobOffer,
    company: str,
    job_description: str | None = None,
    llm: FallbackLLM | None = None,
    min_score: float = Settings.MIN_OVERALL_SCORE_FOR_AUTO_LETTER,
) -> str | None:
    """
    Returns a generated cover letter (in job_offer.description_language,
    falling back to French), or None if the match is too weak to justify
    an auto-generated letter (caller should fall back to manual entry or
    no letter at all).

    `company` is passed separately since JobOffer doesn't carry it --
    it lives on RawJob upstream.
    """
    if match_result.overall_score < min_score:
        return None

    if llm is None:
        raise ValueError("generate_cover_letter requires a FallbackLLM instance.")

    system_prompt = build_cover_letter_system_prompt(job_offer.description_language)
    prompt = build_cover_letter_prompt(candidate, match_result, job_offer, company, job_description)

    draft: CoverLetterDraft = llm.generate_structured(system_prompt, prompt, CoverLetterDraft)
    return draft.letter