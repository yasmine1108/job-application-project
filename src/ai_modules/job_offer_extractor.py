import json
from datetime import datetime
from pathlib import Path

from src.llm.fallback import FallbackLLM
from src.models_job import JobOfferInferenceBatch, RawJob, JobOfferInference, JobOffer


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
    "LOCATION: most jobs include a 'Location:' field extracted by the scraper "
    "— when present and it looks like a real place (city/region/country), "
    "leave the 'location' output field null; the scraped value will be used "
    "as-is and you do not need to repeat it.\n"
    "Some jobs are marked 'Location: NEEDS_EXTRACTION' — this means the "
    "scraper failed to capture a valid location. For ONLY these jobs, read "
    "the full description and extract the actual work location (city/region/"
    "country) if it is stated anywhere in the text. If the description does "
    "not mention a location at all, leave the 'location' output field null "
    "— do not guess or infer a location from unrelated context (e.g. company "
    "headquarters mentioned in passing is not necessarily the job location).\n\n"
    "Do not invent information not present or reasonably implied. If a field "
    "cannot be determined, omit it or leave its list empty."
)


class JobOfferExtractor:
    """Provider-agnostic extractor. Which model(s) actually run this is
    entirely decided by the FallbackLLM passed in.

    output_path is used only for resume/de-dup across runs (crash recovery,
    skip-already-extracted) -- it is NOT how raw jobs get in. Raw jobs come
    in as a list[RawJob] argument, so this can be called directly from an
    in-memory pipeline without touching disk for input.
    """

    def __init__(self, llm: FallbackLLM, output_path: str | Path, batch_size: int = 10):
        self.llm = llm
        self.output_path = Path(output_path)
        self.batch_size = batch_size

    def extract_batch(self, raw_jobs: list[RawJob]) -> dict[str, JobOfferInference]:
        prompt = self._build_batch_prompt(raw_jobs)
        batch = self.llm.generate_structured(SYSTEM_PROMPT, prompt, JobOfferInferenceBatch)
        return {item.job_url: item for item in batch.results}

    def _needs_location_extraction(self, job: RawJob) -> bool:
        """Location is missing, or the scraper mistakenly copied the title
        into the location field (a known scraping bug)."""
        if not job.location or not job.location.strip():
            return True
        if job.title and job.location.strip().lower() == job.title.strip().lower():
            return True
        return False

    def _build_batch_prompt(self, raw_jobs: list[RawJob]) -> str:
        parts = []
        for job in raw_jobs:
            location_line = (
                "Location: NEEDS_EXTRACTION"
                if self._needs_location_extraction(job)
                else f"Location: {job.location}"
            )
            parts.append(
                f"job_url: {job.job_url}\n"
                f"Title: {job.title or 'N/A'}\n"
                f"Company: {job.company or 'N/A'}\n"
                f"{location_line}\n"
                f"Description:\n{job.description or ''}\n"
                f"---"
            )
        return "\n".join(parts)

    def extract_jobs(self, raw_jobs: list[RawJob]) -> list[JobOffer]:
        """Main entry point for the in-memory pipeline. Takes raw jobs
        directly; only reads self.output_path to resume/skip jobs already
        extracted in a previous run, and writes to it after every batch for
        crash recovery -- same pattern as Matcher.run."""
        structured_jobs = self._load_existing_jobs()
        already_done = {job.job_url for job in structured_jobs}

        closed_count = sum(
            1 for j in raw_jobs
            if j.job_url not in already_done and not j.accepting_applications
        )
        to_extract = [
            j for j in raw_jobs
            if j.job_url not in already_done and j.accepting_applications
        ]
        if closed_count:
            print(f"Skipping {closed_count} job(s) no longer accepting applications.")

        for i in range(0, len(to_extract), self.batch_size):
            chunk = to_extract[i:i + self.batch_size]
            try:
                results_by_url = self.extract_batch(chunk)
            except Exception as e:
                print(f"Batch {i}-{i + len(chunk)} failed ({e}), saving progress and stopping.")
                self._write_jobs(self.output_path, structured_jobs)
                raise  # was: break -- caller must know extraction was incomplete

            for raw_job in chunk:
                inference = results_by_url.get(raw_job.job_url)
                if inference is None:
                    print(f"WARNING: no result for {raw_job.job_url}, skipping")
                    continue
                structured_jobs.append(self._build_job_offer(raw_job, inference))

            # write after every successful chunk, not just at the end
            self._write_jobs(self.output_path, structured_jobs)

        return structured_jobs

    def extract_jobs_from_file(self, input_path: str | Path) -> list[JobOffer]:
        """Thin file-based wrapper for standalone/CLI use, e.g. re-running
        extraction on a previously saved scrape without going through the
        full pipeline. Not used by the in-memory pipeline itself."""
        input_path = Path(input_path)
        with input_path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        raw_jobs = [RawJob(**item) if isinstance(item, dict) else item for item in payload]
        return self.extract_jobs(raw_jobs)

    def _build_job_offer(self, raw_job: RawJob, inference: JobOfferInference) -> JobOffer:
        """Reconcile location: prefer the LLM's extracted location only when
        the scraped one was flagged as missing/bad; otherwise keep the
        scraper's value untouched."""
        if self._needs_location_extraction(raw_job) and inference.location:
            raw_job = raw_job.model_copy(update={"location": inference.location})
        return JobOffer.from_raw_and_inference(raw_job, inference)

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