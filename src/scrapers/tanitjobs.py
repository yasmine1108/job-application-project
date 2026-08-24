import json
import os
from datetime import date, datetime

from src.scrapers.job_board_scraper import JobBoardScraper
from src.application_logging import ApplicationLog, save_application_log
from src.ai_modules.cover_letter import generate_cover_letter
from src.llm.fallback import FallbackLLM
from src.matchers.matcher import MatchResult
from src.models import CandidateProfile
from src.models_job import JobOffer, JobStatus, RawJob
from src.scrapers.base_scraper import BaseScraper
from config.settings import Settings

import unicodedata

EMPLOYMENT_TYPE_TRANSLATIONS: dict[str, str] = {
    "temps plein": "full-time",
    "cdi": "full-time",        # permanent contract — closest enum fit
    "cdd": "contract",         # fixed-term contract (not seen yet, but will show up)
    "stage": "internship",
    "sivp": "internship",      # subsidized grad integration program — closest fit, raw string preserved separately
    "intérim": "temporary",
    "temps partiel": "part-time",
    "freelance": "contract",
    "alternance": "internship",
}


def _strip_accents(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))


def translate_employment_type(raw: str | None) -> tuple[str | None, str | None]:
    """Returns (normalized_enum_value, raw_original). Unknown types fall
    back to 'other' rather than crashing on EmploymentType(...) later,
    but the raw string is always preserved regardless."""
    if not raw or not raw.strip():
        return None, None

    key = _strip_accents(raw.strip().lower())
    normalized = EMPLOYMENT_TYPE_TRANSLATIONS.get(key)

    if normalized is None:
        print(f"WARNING: unrecognized employment type '{raw}', defaulting to 'other'")
        normalized = "other"

    return normalized, raw.strip()

WORK_ARRANGEMENT_REMOTE_KEYWORDS = {"remote", "teletravail", "100 remote"}
WORK_ARRANGEMENT_HYBRID_KEYWORDS = {"hybride", "hybrid"}  # not confirmed present yet, but cheap to guard for


def infer_work_arrangement(location: str | None,title: str | None) -> str:
    if not location:
        return "on-site"

    normalized_location = _strip_accents(location.strip().lower())
    normalized_title = _strip_accents(title.strip().lower()) if title else None

    if any(kw in normalized_location for kw in WORK_ARRANGEMENT_HYBRID_KEYWORDS) or (normalized_title and any(kw in normalized_title for kw in WORK_ARRANGEMENT_HYBRID_KEYWORDS)):
        return "hybrid"
    if any(kw in normalized_location for kw in WORK_ARRANGEMENT_REMOTE_KEYWORDS) or (normalized_title and any(kw in normalized_title for kw in WORK_ARRANGEMENT_REMOTE_KEYWORDS)):
        return "remote"
    return "on-site"

class TanitJobsScraper(JobBoardScraper):
    def __init__(self):
        super().__init__(base_url="http://www.tanitjobs.com/")
        
        self.email = Settings.TANITJOBS_EMAIL
        self.password = Settings.TANITJOBS_PASSWORD
        self.output_file = "data/outputs/tanitjobs_links.json"
        self.applications_output_path = "data/outputs/tanitjobs_applications.json"
    
    def is_logged_in(self):
        try:
            # Adjust selector: something only visible when logged in,
            # e.g. an account/profile link or a "logout" link
            self.page.wait_for_selector("a[href*='/logout/']", timeout=8000)
            print("successfully logged in to TanitJobs.")
            return True
        except Exception:
            return False

    def login(self):
        
        cnx_btn = self.page.locator("xpath=/html/body/nav/div/div[4]/ul/li[1]/a")
        cnx_btn.wait_for(state="visible")
        cnx_btn.click()
        self.page.locator("xpath=/html/body/div[4]/div/div[1]/div[1]/div/form/div[1]/input").fill(self.email)
        self.page.locator("xpath=/html/body/div[4]/div/div[1]/div[1]/div/form/div[2]/input").fill(self.password)
        self.page.locator("xpath=/html/body/div[4]/div/div[1]/div[1]/div/form/table/tbody/tr/td[1]/div/input").click()
        self.sb.sleep(5)

    def _is_still_open(self, expiration_date: str | None) -> bool:
        """Return True when the posting is still open compared with today's date."""
        if not expiration_date or not expiration_date.strip():
            return True

        today = date.today()
        try:
            parsed_date = datetime.strptime(expiration_date.strip(), "%d/%m/%Y").date()
            return parsed_date >= today
        except ValueError:
            return True
        
    def _go_to_next_page(self) -> bool:
        next_link = self.page.locator("a.sj-page-btn.sj-arrow").filter(has_text="→")
        if next_link.count() == 0:
            return False
        next_link.first.click()
        self.sb.sleep(5)
        return True

    def _collect_cards_on_current_page(self, cards_per_page_limit):
        job_cards = self.page.locator(".sj-job-card")
        count = job_cards.count()
        print(f"Nombre de cartes détectées : {count}")

        if cards_per_page_limit is not None:
            count = min(count, cards_per_page_limit)

        page_collected = []
        for i in range(count):
            card = job_cards.nth(i)

            job_id = card.get_attribute("id")

            link_el = card.locator("div.sj-card-title a").first
            job_url = self._clean_url(link_el.get_attribute("href"))
            print(f"Job ID: {job_id}, URL: {job_url}")

            if not job_url:
                continue

            title = self._safe_text(lambda: card.locator("div.sj-card-title a").first)
            company = self._safe_text(lambda: card.locator("div.sj-card-company a").first)
            location = self._safe_text(lambda: card.locator("span.sj-loc").first)
            raw_employment_type = self._safe_text(lambda: card.locator("span.sj-type").first)
            employment_type, raw_type_preserved = translate_employment_type(raw_employment_type)
            work_arrangement = infer_work_arrangement(location, title)
            date_posted = self._safe_text(lambda: card.locator("span.sj-card-date").first)

            page_collected.append({
                "job_id": job_id,
                "job_url": job_url,
                "title": title,
                "company": company,
                "location": location,
                "employment_type": employment_type,
                "raw_employment_type": raw_type_preserved,
                "work_arrangement": work_arrangement,
                "date_posted": date_posted,
                "job_status": JobStatus.OPEN,
            })

        return page_collected

    def search_and_collect_links(self, keyword, debug=True, cards_per_page_limit=2, max_pages=None):
        """
        cards_per_page_limit: cap cards read per page (for quickly testing
        a single page's parsing logic). None = read every card on the page.
        max_pages: hard safety cap on pages visited. None = no cap; the loop
        already stops naturally at the first page with zero cards.
        debug: convenience flag for quick manual testing -- caps both to
        small values unless you also pass them explicitly.
        """
        if debug:
            cards_per_page_limit = cards_per_page_limit if cards_per_page_limit is not None else 5
            max_pages = max_pages if max_pages is not None else 1

        logo_link = self.page.locator("a[href='https://www.tanitjobs.com']")
        logo_link.wait_for(state="visible")
        logo_link.click()
        search_input = self.page.get_by_placeholder("Mots Clés")
        search_input.wait_for(state="visible")
        search_input.fill(keyword)
        search_input.press("Enter")

        self.sb.sleep(5)

        collected = []
        page_number = 1
        while True:
            if page_number > 1:
                if not self._go_to_next_page():
                    print(f"No next-page link found after page {page_number - 1}, stopping pagination.")
                    break

            page_collected = self._collect_cards_on_current_page(cards_per_page_limit)
            if not page_collected:
                print(f"Page {page_number}: no cards found, stopping pagination.")
                break

            collected.extend(page_collected)
            self._merge_and_save(page_collected)  # incremental save, same crash-recovery pattern as elsewhere

            if max_pages is not None and page_number >= max_pages:
                print(f"Reached max_pages={max_pages}, stopping.")
                break

            page_number += 1

        print(f"Total de cartes collectées : {len(collected)}")
        return collected

    def _clean_url(self, href):
        """Strip tracking params (backPage, searchID) so the same job
        doesn't get treated as a new URL if it reappears in a later search
        with a different searchID."""
        if not href:
            return None
        return href.split("?")[0]


    def _merge_and_save(self, new_items):
        os.makedirs(os.path.dirname(self.output_file), exist_ok=True)

        existing = []
        if os.path.exists(self.output_file) and os.path.getsize(self.output_file) > 0:
            try:
                with open(self.output_file, "r", encoding="utf-8") as f:
                    existing = json.load(f)
            except json.JSONDecodeError:
                existing = []

        existing_urls = {item["job_url"] for item in existing}
        added = 0
        for item in new_items:
            if item["job_url"] not in existing_urls:
                existing.append(item)
                existing_urls.add(item["job_url"])
                added += 1

        with open(self.output_file, "w", encoding="utf-8") as f:
            json.dump(existing, f, indent=4, ensure_ascii=False)

        print(f"Sauvegarde terminée. Total général : {len(existing)} offres ({added} ajoutées).")

    def extract_job_list(self, collected_links):
        # with open(self.output_file, "r", encoding="utf-8") as f:
        #     cards = json.load(f)
        cards = collected_links

        details_file = "data/outputs/tanitjobs_raw_job_list.json"
        existing = []
        if os.path.exists(details_file) and os.path.getsize(details_file) > 0:
            with open(details_file, "r", encoding="utf-8") as f:
                existing = json.load(f)
        done_urls = {item["job_url"] for item in existing}

        for card in cards:
            if card["job_url"] in done_urls:
                continue
            self.sb.sleep(3)
            details = self.extract_job_details(card["job_url"])
            existing.append({**card, **details})

            os.makedirs(os.path.dirname(details_file), exist_ok=True)
            with open(details_file, "w", encoding="utf-8") as f:
                json.dump(existing, f, indent=4, ensure_ascii=False)

        print(f"Total de cartes détaillées collectées : {len(existing)}")
        return [RawJob.model_validate(item) for item in existing]

    def extract_job_details(self, job_url: str) -> dict:
        self.page.goto(job_url,wait_until="domcontentloaded", timeout=30000)
        self.sb.sleep(3)

        headings = self.page.locator("h3.details-body__title")
        contents = self.page.locator("div.details-body__content.content-text")

        heading_count = headings.count()
        content_count = contents.count()

        if heading_count != content_count:
            print(f"WARNING: {job_url} has {heading_count} headings but {content_count} content divs — structure mismatch")

        sections: dict[str, str] = {}
        for i in range(min(heading_count, content_count)):
            heading_text = headings.nth(i).inner_text().strip()
            content_text = contents.nth(i).inner_text().strip()
            sections[heading_text] = content_text

        description = sections.get("Description de l'emploi", "")
        requirements = sections.get("Exigences de l'emploi", "")
        expiration_raw = sections.get("Date d'expiration")

        full_description = "\n\n".join(part for part in [description, requirements] if part)

        return {
            "description": full_description,
            "expiration_date": expiration_raw,
            "accepting_applications": self._is_still_open(expiration_raw),
        }

    def auto_apply(self, job_url: str, candidate: CandidateProfile, cv_path: str, llm: FallbackLLM, match_result: MatchResult, job_offer: JobOffer, raw_job: RawJob, dry_run: bool = True) -> ApplicationLog:
        print(f"Attempting to auto-apply for job: {job_url}")
        self.page.goto(job_url, wait_until="domcontentloaded", timeout=30000)
        apply_button = self.page.get_by_role("button", name="Postuler maintenant")
        apply_button.wait_for(state="visible", timeout=10000)
        apply_button.click()

        fullname_field = self.page.locator("input[name='name']")
        email_field = self.page.locator("input[name='email']")
        phone_field = self.page.locator("input[name='phone']")
        file_input = self.page.locator('input[type="file"]')
        cover_letter_field = self.page.locator("textarea[name='comments']")

        if fullname_field.input_value().strip() == "":
            fullname_field.fill(candidate.personal_information.full_name)
        if email_field.input_value().strip() == "":
            email_field.fill(candidate.personal_information.email)
        if phone_field.input_value().strip() == "":
            phone_field.fill(candidate.personal_information.phone)
        if file_input and cv_path:
            print(f"Uploading CV from {cv_path}")
            file_input.set_input_files(cv_path)

        cover_letter = generate_cover_letter(
            candidate=candidate,
            match_result=match_result,
            job_offer=job_offer,
            company=raw_job.company,
            job_description=raw_job.description,
            llm=llm,
        )
        cover_letter_field.fill(cover_letter or "")

        # Read back exactly what's on the page -- not what we *think* we filled --
        # so a logged dry run reflects reality (pre-filled fields we skipped included).
        payload = {
            "job_url": job_url,
            "name": fullname_field.input_value(),
            "email": email_field.input_value(),
            "phone": phone_field.input_value(),
            "cv_path": cv_path,
            "cover_letter": cover_letter,
        }

        submit_button = self.page.get_by_role("button", name="Envoyer la candidature")
        submit_button.wait_for(state="visible", timeout=10000)

        cover_letter_source = "generated" if cover_letter else "none"
        if dry_run:
            print(f"[DRY RUN] Not submitting. Payload for {job_url}")
            log = ApplicationLog(job_url=job_url, candidate_id=candidate.candidate_id, dry_run=True, submitted=False, payload=payload, cover_letter_source=cover_letter_source)
        else:
            submit_button.click()
            self.page.wait_for_load_state("networkidle")
            log = ApplicationLog(job_url=job_url, candidate_id=candidate.candidate_id, dry_run=False, submitted=True, payload=payload, cover_letter_source=cover_letter_source)

        self._save_application_log(log)
        return log

    def _save_application_log(self, log: ApplicationLog) -> None:
        save_application_log(self.applications_output_path, log)