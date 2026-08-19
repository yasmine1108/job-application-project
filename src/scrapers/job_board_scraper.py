"""
Job-board scraper abstraction.

BaseScraper already standardizes browser lifecycle (start_browser, login,
close_browser). This layer standardizes the job-board-specific operations
on top of it, so the agent can call any scraper through one interface and
never needs to know or care whether a given job_url is TanitJobs, LinkedIn,
or something added later.
"""

from abc import ABC, abstractmethod
from urllib.parse import urlparse

from src.scrapers.base_scraper import BaseScraper
from src.models import CandidateProfile
from src.matchers.matcher import MatchResult
from src.models_job import JobOffer, RawJob
from src.llm.fallback import FallbackLLM
from src.application_logging import ApplicationLog


class JobBoardScraper(BaseScraper, ABC):
    @abstractmethod
    def search_and_collect_links(self, keyword: str) -> list[dict]:
        """Search the board for `keyword`, persist/merge found job links,
        and return the newly collected entries."""
        ...

    @abstractmethod
    def extract_job_list(self) -> list[RawJob]:
        """Visit each collected link not yet detailed, extract full raw
        job data, and return the full list of RawJob."""
        ...

    @abstractmethod
    def auto_apply(
        self,
        job_url: str,
        candidate: CandidateProfile,
        cv_path: str,
        llm: FallbackLLM,
        match_result: MatchResult,
        job_offer: JobOffer,
        raw_job: RawJob,
        dry_run: bool = True,
    ) -> ApplicationLog:
        ...


# --- Registry: agent looks up a scraper by domain, never imports a
# concrete scraper class by name. Add a new site by adding one line here.
SCRAPER_REGISTRY: dict[str, type[JobBoardScraper]] = {}


def register_scraper(domain: str, scraper_cls: type[JobBoardScraper]) -> None:
    SCRAPER_REGISTRY[domain] = scraper_cls


def get_scraper_for_url(job_url: str) -> JobBoardScraper:
    domain = urlparse(job_url).netloc.replace("www.", "")
    for key, cls in SCRAPER_REGISTRY.items():
        if key in domain:
            return cls()
    raise ValueError(f"No scraper registered for URL: {job_url} (domain: {domain})")
