import json
from datetime import datetime
from pathlib import Path


from google import genai
from google.genai import types

from config.settings import Settings
from src.models_job import JobOfferInferenceBatch, RawJob, JobOfferInference, JobOffer


class GeminiJobExtractor:
    MODEL_NAME = Settings.GEMINI_MODEL_NAME
    BATCH_SIZE = 10 

    SYSTEM_PROMPT = (
    "You are an exhaustive information extraction system. You will be given a "
    "raw job posting. Extract structured attributes per the response schema.\n\n"
    "CRITICAL: Be exhaustive, not selective. Job descriptions in French/English "
    "often list requirements across multiple sections (Missions, Profil, "
    "Compétences techniques). Scan the ENTIRE text, including bullet lists and "
    "parenthetical examples (e.g. 'librairies Python (Pandas, Polars, "
    "Scikit-learn...)' means Pandas AND Polars AND Scikit-learn AND any other "
    "named library are ALL separate skills).\n\n"
    "Include ALL of the following skill types, not just programming languages:\n"
    "- Programming languages (Python, SQL, JavaScript)\n"
    "- Tools/libraries/frameworks (git, Pandas, QGIS, TensorFlow)\n"
    "- Domain knowledge (mobility/transport engineering, GIS)\n"
    "- Soft skills stated explicitly (esprit analytique, autonomie, travail "
    "en équipe, capacité de rédaction) — these are real requirements, extract "
    "them with category=soft, do not skip them because they are not technical.\n\n"
    "required_experience must capture the FULL free-text experience requirement "
    "as stated (e.g. '2 to 5 years in data science and software development, "
    "ideally in the transport sector'), even when min_years_experience is also "
    "filled numerically — they are not redundant, populate both.\n\n"
    "required_languages: scan for spoken/human language requirements (e.g. "
    "'bon niveau d'anglais', 'fluent English', 'courant en français') — these "
    "are commonly stated near the end of requirements sections and are easy "
    "to miss; check specifically before finalizing your answer.\n\n"
    "Do NOT include academic degrees in required_certifications — degrees "
    "belong exclusively in required_education. A certification is a "
    "professional credential (AWS Certified, PMP), never a degree.\n\n"
    "Do not confuse programming languages with spoken languages.\n\n"
    "Do not invent information not present or reasonably implied. If a field "
    "cannot be determined, omit it or leave its list empty."
)
    def __init__(self):
        api_key = Settings.GEMINI_API_KEY
        self.client = genai.Client(api_key=api_key)
        self.input_path = Path("data/outputs/linkedin_raw_job_list.json")
        self.output_path = Path("data/outputs/linkedin_structured_jobs.json")

    def extract_batch(self, raw_jobs: list[RawJob]) -> dict[str, JobOfferInference]:
        prompt = self._build_batch_prompt(raw_jobs)

        response = self.client.models.generate_content(
            model=self.MODEL_NAME,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=self.SYSTEM_PROMPT,
                response_mime_type="application/json",
                response_schema=JobOfferInferenceBatch,
                temperature=0,
            ),
        )

        batch = JobOfferInferenceBatch.model_validate(json.loads(response.text))
        return {item.job_url: item for item in batch.results}

    def _build_batch_prompt(self, raw_jobs: list[RawJob]) -> str:
        parts = []
        for job in raw_jobs:
            parts.append(
                f"job_url: {job.job_url}\n"
                f"Title: {job.title or 'N/A'}\n"
                f"Company: {job.company or 'N/A'}\n"
                f"Location: {job.location or 'N/A'}\n"
                f"Description:\n{job.description or ''}\n"
                f"---"
            )
        return "\n".join(parts)

    def extract_jobs_from_file(self) -> list[JobOffer]:
        with self.input_path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)

        raw_jobs = [RawJob(**item) if isinstance(item, dict) else item for item in payload]

        # resume support: skip jobs already extracted in a previous run
        structured_jobs = self._load_existing_jobs()
        already_done = {job.job_url for job in structured_jobs}
        raw_jobs = [j for j in raw_jobs if j.job_url not in already_done]

        for i in range(0, len(raw_jobs), self.BATCH_SIZE):
            chunk = raw_jobs[i:i + self.BATCH_SIZE]
            try:
                results_by_url = self.extract_batch(chunk)
            except Exception as e:
                print(f"Batch {i}-{i+len(chunk)} failed ({e}), saving progress and stopping.")
                self._write_jobs(self.output_path, structured_jobs)
                break

            for raw_job in chunk:
                inference = results_by_url.get(raw_job.job_url)
                if inference is None:
                    print(f"WARNING: no result for {raw_job.job_url}, skipping")
                    continue
                structured_jobs.append(JobOffer.from_raw_and_inference(raw_job, inference))

            # write after every successful chunk, not just at the end
            self._write_jobs(self.output_path, structured_jobs)

        return structured_jobs

    def _load_existing_jobs(self) -> list[JobOffer]:
        if not self.output_path.exists():
            return []
        with self.output_path.open("r", encoding="utf-8") as handle:
            try:
                data = json.load(handle)
            except json.JSONDecodeError:
                return []
        return [JobOffer.model_validate(item) for item in data]

    def _write_jobs(self, output_path: Path, jobs: list[JobOffer]) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)

        serializable_jobs = []
        for job in jobs:
            job_data = job.model_dump() if hasattr(job, "model_dump") else job.dict()
            for key, value in list(job_data.items()):
                if isinstance(value, datetime):
                    job_data[key] = value.isoformat()
            serializable_jobs.append(job_data)

        with output_path.open("w", encoding="utf-8") as handle:
            json.dump(serializable_jobs, handle, indent=4, ensure_ascii=False)