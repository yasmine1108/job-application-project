import json
import os
import re
import unicodedata
from datetime import datetime
from pathlib import Path

import phonenumbers
import pycountry
from babel.dates import get_month_names

from src.ai_modules.cover_letter import generate_cover_letter, save_cover_letter_as_pdf
from src.application_logging import ApplicationLog, FieldFillLog, save_application_log, save_field_fill_log
from src.llm.fallback import FallbackLLM
from src.matchers.country_normalize import normalize_country
from src.matchers.matcher import MatchResult
from src.models import CandidateProfile, Experience, Education
from src.scrapers.job_board_scraper import JobBoardScraper
from src.scrapers.base_scraper import BaseScraper
from src.models_job import JobOffer, JobStatus, RawJob
from config.settings import Settings


# ---------------------------------------------------------------------------
# Deterministic normalization helpers (phone country code, months, location).
# Same philosophy as src/matchers/country_normalize.py: these are small,
# closed vocabularies -- solved with lookup tables, not LLM calls.
# ---------------------------------------------------------------------------

def _strip_accents(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))


def extract_phone_country_code(phone: str | None) -> str | None:
    """Returns ISO 3166-1 alpha-2 (e.g. 'TN') only when the phone string
    itself contains an explicit country calling code (+216..., 00216...).
    Returns None otherwise -- do not guess a country from a bare local
    number, that's not something a parser (or an LLM) can resolve reliably."""
    if not phone or not phone.strip():
        return None
    try:
        parsed = phonenumbers.parse(phone.strip(), None)  # region=None: explicit-code-only parsing
        if phonenumbers.is_valid_number(parsed):
            return phonenumbers.region_code_for_number(parsed)
    except phonenumbers.NumberParseException:
        pass
    return None


def resolve_phone_country_code(phone: str | None) -> str | None:
    """Lowercase ISO alpha-2, matching LinkedIn's <option value="ae"> style."""
    code = extract_phone_country_code(phone)
    return code.lower() if code else None


def _build_month_lookup() -> dict[str, str]:
    lookup: dict[str, str] = {}

    # Always use Babel's wide English names as the output.
    # Accept both French and English full/abbreviated names as input.
    en_wide = get_month_names("wide", locale="en")
    en_abbreviated = get_month_names("abbreviated", locale="en")

    fr_wide = get_month_names("wide", locale="fr")
    fr_abbreviated = get_month_names("abbreviated", locale="fr")

    for num, name in en_wide.items():
        lookup[_strip_accents(name.strip().lower()).rstrip(".")] = en_wide[num]

    for num, name in en_abbreviated.items():
        lookup[_strip_accents(name.strip().lower()).rstrip(".")] = en_wide[num]

    for num, name in fr_wide.items():
        lookup[_strip_accents(name.strip().lower()).rstrip(".")] = en_wide[num]

    for num, name in fr_abbreviated.items():
        lookup[_strip_accents(name.strip().lower()).rstrip(".")] = en_wide[num]

    return lookup


_MONTH_LOOKUP = _build_month_lookup()
_YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")


def parse_month_year(raw: str | None) -> tuple[str | None, str | None]:
    """'Sept. 2024' / 'septembre 2024' / 'September 2024' -> ('September', '2024').
    Returns (None, None) for unparseable text (e.g. 'Present') -- callers
    should route that through is_current, not guess a month from it."""
    if not raw or not raw.strip():
        return None, None

    year_match = _YEAR_RE.search(raw)
    year = year_match.group(0) if year_match else None

    for token in re.findall(r"[A-Za-zÀ-ÿ]+", raw):
        key = _strip_accents(token.lower()).rstrip(".")
        if key in _MONTH_LOOKUP:
            return _MONTH_LOOKUP[key], year

    return None, year


def anglicize_location(raw_location: str | None) -> str | None:
    """'Tunis, Tunisie' -> 'Tunis, Tunisia'. Only the country token is
    translated (via the existing country_normalize lookup) -- city names
    are proper nouns and are almost always identical across languages."""
    if not raw_location or not raw_location.strip():
        return raw_location

    parts = [p.strip() for p in raw_location.split(",")]
    country_code = normalize_country(parts[-1])
    if country_code:
        country = pycountry.countries.get(alpha_2=country_code)
        if country:
            parts[-1] = country.name
    return ", ".join(parts)


class LinkedInScraper(JobBoardScraper):

    def __init__(self):
        super().__init__(base_url="http://www.linkedin.com/")
        self.EMPLOYMENT_TYPES = [
            "full-time", "part-time", "internship", "contract",
            "temporary", "volunteer", "other", "freelance"
        ]
        self.WORK_ARRANGEMENTS = ["remote", "hybrid", "on-site", "onsite"]
        self.email = Settings.LINKEDIN_EMAIL
        self.password = Settings.LINKEDIN_PASSWORD
        self.output_file = "data/outputs/linkedin_links.json"
        self.jobs_list_file = "data/outputs/linkedin_raw_job_list.json"
        self.structured_jobs = "data/outputs/structured_jobs.json"
        self.applications_output_path = "data/outputs/linkedin_applications.json"
        self.field_fill_log_path = "data/outputs/linkedin_field_fills.json"

        # set at the start of each auto_apply call, used by _log_field so
        # every fill-site doesn't need to thread job_url/candidate_id through
        self._current_job_url: str | None = None
        self._current_candidate_id: str | None = None
        self._current_payload: dict = {}

    def is_logged_in(self):
        try:
            # Nav search bar only shows once authenticated
            self.page.wait_for_selector(
                "input[placeholder='Search']", timeout=8000
            )
            return True
        except Exception:
            return False

    def login(self):
        print("Connexion à LinkedIn en cours...")

        self.page.get_by_role("link", name="Sign in", exact=True).click()
        self.sb.sleep(5)
        email_input = self.page.get_by_role("textbox", name="Email or phone")
        email_input.wait_for(state="visible")
        password_input = self.page.get_by_role("textbox", name="Password")
        password_input.wait_for(state="visible")

        signinbutton = self.page.get_by_role("button", name="Sign in", exact=True)
        signinbutton.wait_for(state="visible")
        email_input.fill(self.email)
        password_input.fill(self.password)
        signinbutton.click()

        print(f"Titre de la page : {self.page.title()}")

    def search_and_collect_links(self, keyword, debug=True, max_number_links=None):
        if debug: 
            max_number_links = max_number_links if max_number_links is not None else 5
        self.sb.sleep(5)
# Locate and click the fake search button trigger
        search_trigger = self.page.get_by_role("button", name="Search", exact=True)
        search_trigger.wait_for(state="visible")
        search_trigger.click()
        search_input = self.page.get_by_placeholder("Search")
        search_input.wait_for(state="visible")
        search_input.fill(keyword)
        search_input.press("Enter")
        print(f"Recherche de liens pour le mot-clé : {keyword}")
        jobsbuttonvisible = self.page.get_by_role("radio", name="Filter by Jobs")
        jobsbuttonvisible.wait_for(state="visible")
        jobsbuttonvisible.click()

        self.sb.sleep(10)
        job_cards = self.page.locator("div[role='button'][componentkey^='job-card-component-ref-']")
        job_cards.first.wait_for(state="visible")

        cards_count = job_cards.count()
        print(f"Nombre de cartes détectées : {cards_count}")

        if debug and max_number_links is not None:
            cards_count = min(cards_count, max_number_links)
            print(f"Limitation du nombre de cartes à {cards_count} pour le débogage.")

        urls = []
        for i in range(cards_count):
            card = job_cards.nth(i)
            component_key = card.get_attribute("componentkey")
            if component_key:
                job_id = component_key.split('-')[-1]
                job_url = f"https://www.linkedin.com/jobs/view/{job_id}/"
                if job_url not in urls:
                    urls.append(job_url)

        print(f"Total de liens uniques collectés : {len(urls)}")
        os.makedirs(os.path.dirname(self.output_file), exist_ok=True)

        urls_existantes = []
        if os.path.exists(self.output_file) and os.path.getsize(self.output_file) > 0:
            try:
                with open(self.output_file, "r", encoding="utf-8") as f:
                    urls_existantes = json.load(f)
                print(f"{len(urls_existantes)} anciennes URLs chargées depuis le fichier.")
            except json.JSONDecodeError:
                urls_existantes = []

        compteur_nouveaux = 0
        for url in urls:
            if url not in urls_existantes:
                urls_existantes.append(url)
                compteur_nouveaux += 1

        with open(self.output_file, "w", encoding="utf-8") as f:
            json.dump(urls_existantes, f, indent=4, ensure_ascii=False)

        print(f"Sauvegarde terminée. Total général : {len(urls_existantes)} URLs ({compteur_nouveaux} ajoutées).")
        return urls

    def extract_job_list(self, collected_links):
        collected_links = collected_links or []
 
        all_jobs: list[RawJob] = []
        if os.path.exists(self.jobs_list_file) and os.path.getsize(self.jobs_list_file) > 0:
            try:
                with open(self.jobs_list_file, "r", encoding="utf-8") as f:
                    saved_jobs = json.load(f)
                all_jobs = [RawJob(**job) if isinstance(job, dict) else job for job in saved_jobs]
            except json.JSONDecodeError:
                all_jobs = []
 
        jobs_by_url: dict[str, RawJob] = {job.job_url: job for job in all_jobs if job.job_url}
 
        new_urls = [u for u in collected_links if u not in jobs_by_url]
 
        for url in new_urls:
            self.sb.sleep(5)
            self.page.goto(url)
 
            job_offer = self._extract_via_dom()
            job_offer.job_url = url
            job_offer.job_id = url.split("/")[-2]
            locator = self.page.get_by_text("No longer accepting applications", exact=False)
            if locator.count() > 0:
                job_offer.accepting_applications = False
 
            job_links = self.page.locator(f'a[href*="{url}"]')
            texts = []
            for i in range(job_links.count()):
                text = job_links.nth(i).inner_text().strip()
                if text:
                    texts.append(text)
 
            work_arrangement = None
            employment_type = None
            for attribute in texts:
                if attribute.lower() in self.WORK_ARRANGEMENTS:
                    work_arrangement = attribute.lower()
                if attribute.lower() in self.EMPLOYMENT_TYPES:
                    employment_type = attribute.lower()
 
            job_offer.work_arrangement = work_arrangement
            job_offer.employment_type = employment_type
            job_offer.easy_apply = self.page.locator("button[aria-label*='Easy Apply']").count() > 0
 
            jobs_by_url[url] = job_offer
            all_jobs.append(job_offer)  
 
        serializable_jobs = []
        for job in all_jobs:
            job_data = job.model_dump() if hasattr(job, "model_dump") else job.dict()
            for key, value in list(job_data.items()):
                if isinstance(value, (datetime,)):
                    job_data[key] = value.isoformat()
            serializable_jobs.append(job_data)
 
        with open(self.jobs_list_file, "w", encoding="utf-8") as f:
            json.dump(serializable_jobs, f, indent=4, ensure_ascii=False)

 
        return [jobs_by_url[u] for u in collected_links if u in jobs_by_url]


    def _extract_via_dom(self):
        parts = self.page.title().split(" | ")
        return RawJob(
            title=parts[0] if parts else "",
            company=self._safe_text(lambda: self.page.locator("a[href*='/company/']").first),
            location=self._safe_text(lambda: self.page.locator("text=/Remote|Hybrid|On-site|(?:[A-ZÀ-ÿ][A-Za-zÀ-ÿ-]+(?:, [A-ZÀ-ÿ][A-Za-zÀ-ÿ-]+)+)/").first),
            description=self._safe_text(lambda: self.page.locator("div:has(h2:text-matches('About the job', 'i')) ~ p").first),
            date_posted=self._safe_text(lambda: self.page.locator(
                r"text=/\b(?:\d+\+?\s+)?(?:hour|day|week|month|year)s?\s+ago\b/i").first),
        )
    def _mark_job_closed(self, raw_job: RawJob, job_offer: JobOffer) -> None:
        """Called when the job page itself reports it's no longer accepting
        applications -- discovered live, at apply time.
 
        Updates both in-memory objects so the rest of this run treats the
        job as closed, and persists the correction back to the raw job
        list file so future runs skip it via matcher.py's existing
        `job_status == CLOSED` hard filter, instead of re-scoring and
        re-attempting a job that's already gone."""
        
        raw_job.accepting_applications = False
        job_offer.job_status = JobStatus.CLOSED
 
        self._persist_raw_job_update(raw_job)
        self._persist_job_offer_update(job_offer)
 
    def _persist_raw_job_update(self, raw_job: RawJob) -> None:
        """Finds this job by job_url in linkedin_raw_job_list.json and
        overwrites its entry with the current (now-closed) state. Silent
        no-op if the file or entry isn't found -- this is a best-effort
        correction for future runs, not something worth crashing the
        current apply pass over."""
        if not os.path.exists(self.jobs_list_file) or os.path.getsize(self.jobs_list_file) == 0:
            return
        try:
            with open(self.jobs_list_file, "r", encoding="utf-8") as f:
                existing = json.load(f)
        except json.JSONDecodeError:
            print(f"WARNING: could not read {self.jobs_list_file} to persist closed-job status, skipping")
            return
 
        raw_job_dict = raw_job.model_dump(mode="json")
        updated = False
        for i, item in enumerate(existing):
            if item.get("job_url") == raw_job.job_url:
                existing[i] = raw_job_dict
                updated = True
                break
 
        if not updated:
            print(f"WARNING: job_url {raw_job.job_url} not found in {self.jobs_list_file}, could not persist closed status")
            return
 
        with open(self.jobs_list_file, "w", encoding="utf-8") as f:
            json.dump(existing, f, indent=4, ensure_ascii=False)
        print(f"Persisted closed status for {raw_job.job_url} to {self.jobs_list_file}")

    def _persist_job_offer_update(self, job_offer: JobOffer) -> None:
        """Persist a JobOffer update in structured_jobs.json by
        matching on job_url and overwriting the stored entry with the current
        state. This keeps follow-up runs aligned with the last known status
        without re-scoring or re-attempting already-closed jobs."""
        if not os.path.exists(self.structured_jobs) or os.path.getsize(self.structured_jobs) == 0:
            return
        try:
            with open(self.structured_jobs, "r", encoding="utf-8") as f:
                existing = json.load(f)
        except json.JSONDecodeError:
            print(f"WARNING: could not read {self.structured_jobs} to persist JobOffer update, skipping")
            return

        job_offer_dict = job_offer.model_dump(mode="json")
        for key, value in list(job_offer_dict.items()):
            if isinstance(value, datetime):
                job_offer_dict[key] = value.isoformat()

        updated = False
        for i, item in enumerate(existing):
            if item.get("job_url") == job_offer.job_url:
                existing[i] = job_offer_dict
                updated = True
                break

        if not updated:
            print(f"WARNING: job_url {job_offer.job_url} not found in {self.structured_jobs}, could not persist JobOffer update")
            return

        with open(self.structured_jobs, "w", encoding="utf-8") as f:
            json.dump(existing, f, indent=4, ensure_ascii=False)
        print(f"Persisted JobOffer update for {job_offer.job_url} to {self.structured_jobs}")


    # -----------------------------------------------------------------
    # Field-fill logging -- replaces console prints. Every field touched
    # during a page-fill gets one persisted record (data/outputs/
    # linkedin_field_fills.json), same append-only pattern as
    # ApplicationLog, so a run's behavior is auditable after the fact.
    # -----------------------------------------------------------------

    def _log_field(self, page: str, field: str, value: str | None, status: str, note: str | None = None) -> None:
        log = FieldFillLog(
            job_url=self._current_job_url or "",
            candidate_id=self._current_candidate_id or "",
            page=page,
            field=field,
            value=value,
            status=status,
            note=note,
        )
        save_field_fill_log(self.field_fill_log_path, log)
        # keep a concise console trace too -- useful for live debugging,
        # the JSON file is the durable record
        if value is not None and status in ("filled", "already_present"):
            self._current_payload.setdefault(page, {})[field] = value

        print(f"[{status.upper()}] {page}.{field} = {value!r}" + (f" ({note})" if note else ""))

    # -----------------------------------------------------------------
    # Generic helpers used across pages
    # -----------------------------------------------------------------

    def _upload_via_button(self, button_locator, file_path: str):
        """LinkedIn's upload buttons don't expose <input type='file'> in an
        obvious/labelled way -- they trigger the native OS file chooser
        directly. expect_file_chooser intercepts that dialog rather than
        hunting for a hidden input element."""
        with self.page.expect_file_chooser() as fc_info:
            button_locator.click()
        file_chooser = fc_info.value
        file_chooser.set_files(file_path)

    def _fill_typeahead_location(self, location_field, location_text: str) -> bool:
        """LinkedIn's location field only registers a value when a suggestion
        is selected from the dropdown -- fill() alone doesn't trigger the
        debounced autocomplete (it skips real keystroke events), and typing
        text without selecting a suggestion leaves the underlying value unset.
        Returns True if a suggestion was successfully selected."""
        if not location_text:
            return False

        location_field.click()
        location_field.press_sequentially(location_text, delay=80)
        self.page.wait_for_timeout(1200)  # let the debounced suggestion search resolve

        suggestions = self.page.locator("[role='listbox'] [role='option']")
        try:
            suggestions.first.wait_for(state="visible", timeout=5000)
        except Exception as e:
            self._log_field("personal_info", "location", location_text, status="warning", note=f"no suggestion appeared: {e}")
            return False

        # prefer a suggestion whose text contains the country we typed, in
        # case the city name alone is ambiguous across countries
        country_token = location_text.split(",")[-1].strip().lower()
        count = suggestions.count()
        chosen = suggestions.first
        for i in range(count):
            option_text = suggestions.nth(i).inner_text().strip().lower()
            if country_token and country_token in option_text:
                chosen = suggestions.nth(i)
                break

        chosen.click()
        return True

    def _fill_textbox(self, field, value: str | None, page: str, field_name: str) -> None:
        """Fill a text field only if the candidate has a value AND the
        field is currently empty. Missing candidate data -> skip silently
        (logged as 'skipped'), never invent a value."""
        if not value:
            self._log_field(page, field_name, None, status="skipped", note="no value on candidate profile")
            return
        if field.count() == 0:
            return  # field not present on this page at all -- nothing to log, it simply doesn't exist here
        try:
            if field.input_value().strip() != "":
                self._log_field(page, field_name, value, status="already_present")
                return
            field.last.fill(value)
            self._log_field(page, field_name, value, status="filled")
        except Exception as e:
            self._log_field(page, field_name, value, status="error", note=str(e))

    def _select_option(self, select_locator, value: str | None, page: str, field_name: str) -> None:
        if not value:
            self._log_field(page, field_name, None, status="skipped", note="no value to select")
            return
        if select_locator.count() == 0:
            return
        try:
            select_locator.select_option(label=value)
            self._log_field(page, field_name, value, status="filled")
        except Exception as e:
            self._log_field(page, field_name, value, status="error", note=str(e))

    def _toggle_current_checkbox(self, text_locator, page: str, field_name: str) -> bool:
        """Best-guess: the 'I currently work here' / 'I currently attend
        this institution' text is clicked directly (LinkedIn's markup
        wraps these as a clickable label, per the stub locators). We try
        to read an associated checkbox's checked state first to avoid
        toggling it back off on a re-run; if no checkbox can be located
        nearby, we click once and log a warning that state wasn't verified."""
        if text_locator.count() == 0:
            self._log_field(page, field_name, None, status="skipped", note="'currently' toggle not present on this page")
            return False

        nearby_checkbox = text_locator.locator("input[type='checkbox']")
        already_checked = False
        checkbox_found = nearby_checkbox.count() > 0
        if checkbox_found:
            print(f"Found {nearby_checkbox.count()} checkbox(es) near the 'currently' label.")
            try:
                already_checked = nearby_checkbox.first.is_checked()
                print(f"Checkbox is already checked: {already_checked}")
            except Exception:
                checkbox_found = False
 
        if already_checked:
            self._log_field(page, field_name, "checked", status="already_present")
            return True
 
        text_locator.click()
        note = None if checkbox_found else "no associated checkbox found -- clicked label without verifying prior state"
        self._log_field(page, field_name, "checked", status="filled", note=note)
        return True


    # -----------------------------------------------------------------
    # Page handlers -- each one checks whether its markers are present
    # and, if so, fills whatever it can. Multiple handlers can fire on
    # the same page (e.g. CV + cover letter uploads on one screen).
    # -----------------------------------------------------------------

    def _fill_personal_info_page(self, modal, candidate: CandidateProfile):
        page = "personal_info"
        fname_field = modal.get_by_label("First name").or_(modal.get_by_label("Prénom"))
        lname_field = modal.get_by_label("Last name").or_(modal.get_by_label("Nom"))
        phone_code_dropdown = modal.get_by_label("Phone country code")
        phone_number_field = modal.locator("input[type='tel']")
        email_dropdown = modal.get_by_label("Email address").or_(modal.get_by_label("Adresse e-mail"))
        location_field = modal.get_by_placeholder("Enter city or location")

        name_parts = (candidate.personal_information.full_name or "").split(" ", 1)
        first_name = name_parts[0] if name_parts else None
        last_name = name_parts[1] if len(name_parts) > 1 else None

        self._fill_textbox(fname_field, first_name, page, "first_name")
        self._fill_textbox(lname_field, last_name, page, "last_name")

        if phone_code_dropdown.count() > 0 and phone_code_dropdown.last.input_value().strip() == "":
            code = resolve_phone_country_code(candidate.personal_information.phone)
            if code:
                try:
                    phone_code_dropdown.last.select_option(value=code)
                    self._log_field(page, "phone_country_code", code, status="filled")
                except Exception as e:
                    self._log_field(page, "phone_country_code", code, status="error", note=str(e))
            else:
                self._log_field(page, "phone_country_code", None, status="skipped", note="no explicit country code in phone number")

        self._fill_textbox(phone_number_field, candidate.personal_information.phone, page, "phone_number")

        if email_dropdown.count() > 0 and email_dropdown.last.input_value().strip() == "":
            email = candidate.personal_information.email
            if email:
                try:
                    email_dropdown.last.select_option(value=email)
                    self._log_field(page, "email", email, status="filled")
                except Exception as e:
                    self._log_field(page, "email", email, status="error", note=str(e))
            else:
                self._log_field(page, "email", None, status="skipped", note="no email on candidate profile")

        if location_field.count() > 0 and location_field.last.input_value().strip() == "":
            raw_location = getattr(candidate.personal_information, "location", None)
            if raw_location:
                english_location = anglicize_location(raw_location)
                selected = self._fill_typeahead_location(location_field.last, english_location)
                self._log_field(page, "location", english_location, status="filled" if selected else "warning")
            else:
                self._log_field(page, "location", None, status="skipped", note="no location on candidate profile")

    def _fill_cv_upload(self, modal, cv_path: str):
        page = "cv"
        resume_button = modal.get_by_role("button", name="Upload resume")
        if resume_button.count() == 0:
            return
        if not cv_path:
            self._log_field(page, "resume", None, status="skipped", note="no cv_path provided")
            return
        self._upload_via_button(resume_button.first, cv_path)
        self._log_field(page, "resume", cv_path, status="filled")

    def _fill_cover_letter_upload(self, modal, cover_letter_pdf_path: Path | None):
        page = "cover_letter"
        # scope to the container that has both the "Cover letter" heading
        # and an "Upload" button, so we don't grab the CV's Upload button
        cover_letter_section = modal.locator("div").filter(
            has_text=re.compile(r"cover letter|lettre de motivation", re.IGNORECASE)
        ).filter(
            has_text=re.compile(r"upload|t[ée]l[ée]charger", re.IGNORECASE)
        )
        cover_letter_button = cover_letter_section.get_by_role("button", name=re.compile(r"^upload$|^t[ée]l[ée]charger$", re.IGNORECASE))
        if cover_letter_button.count() == 0:
            return
        if cover_letter_pdf_path:
            self._upload_via_button(cover_letter_button.first, str(cover_letter_pdf_path))
            self._log_field(page, "cover_letter_file", str(cover_letter_pdf_path), status="filled")
        else:
            self._log_field(page, "cover_letter_file", None, status="skipped", note="no cover letter was generated")

    def _experience_already_filled(self, modal) -> bool:
        return modal.get_by_role("button", name=re.compile(r"edit,?\s*work experience", re.IGNORECASE)).count() > 0

    def _fill_experience_entry(self, modal, exp: Experience) -> None:
        page = "experience"

        title_field = modal.get_by_role("textbox", name="Your title")
        company_field = modal.get_by_role("textbox", name="Company")
        city_field = modal.get_by_role("textbox", name="City")
        description_field = modal.get_by_role("textbox", name="Description")
        current_toggle = modal.get_by_text("I currently work here")
        start_month_select = modal.locator("select", has_text="Month").first
        end_month_select = modal.locator("select", has_text="Month").last
        start_year_select = modal.locator("select", has_text="Year").first
        end_year_select = modal.locator("select", has_text="Year").last

        self._fill_textbox(title_field, exp.job_title, page, "title")
        self._fill_textbox(company_field, exp.company, page, "company")
        self._fill_textbox(city_field, exp.location, page, "city")
        self._fill_textbox(description_field, str(exp.description or "") + ", ".join(exp.responsibilities), page, "description")

        is_current = exp.is_current
        start_month, start_year = parse_month_year(exp.start_date)
        self._select_option(start_month_select, start_month, page, "start_month")
        self._select_option(start_year_select, start_year, page, "start_year")

        print("is_current:", is_current)
        if is_current:
            toggled = self._toggle_current_checkbox(current_toggle, page, "currently_working")
            if toggled:
                return  # end-date selects are typically disabled/hidden once checked
            if toggled is False:
                self._log_field(page, "currently_working", "checked", status="warning", note="could not check 'currently working' checkbox")
                now = datetime.now()
                end_month, end_year = parse_month_year(now.strftime("%B %Y"))
                self._select_option(end_month_select, end_month, page, "end_month")
                self._select_option(end_year_select, end_year, page, "end_year")
                return

        end_month, end_year = parse_month_year(exp.end_date)
        self._select_option(end_month_select, end_month, page, "end_month")
        self._select_option(end_year_select, end_year, page, "end_year")

    def _fill_experience_page(self, modal, candidate: CandidateProfile):
        page = "experience"
        if self._experience_already_filled(modal):
            self._log_field(page, "entry", None, status="skipped", note="already pre-filled by LinkedIn (edit button present)")
            return

        add_button = modal.get_by_role("button", name=re.compile(r"add more|add work experience|ajouter", re.IGNORECASE))
        if add_button.count() == 0:
            self._log_field(page, "entry", None, status="skipped", note="no add button and no pre-filled entry detected")
            return

        for exp in candidate.experience:
            if not exp.job_title and not exp.company:
                self._log_field(page, "entry", None, status="skipped", note="experience entry has neither title nor company")
                continue

            add_button.first.click()
            self.page.wait_for_timeout(800)
            self._fill_experience_entry(modal, exp)

            # re-locate in case the DOM re-rendered after adding an entry
            add_button = modal.get_by_role("button", name=re.compile(r"add more|add work experience|ajouter", re.IGNORECASE))
            if add_button.count() == 0:
                break

    def _education_already_filled(self, modal) -> bool:
        has_edit_svg = modal.locator("svg#edit-medium").count() > 0
        has_edit_button = modal.get_by_role("button", name=re.compile(r"^edit\b.*|edit formation", re.IGNORECASE)).count() > 0
        return has_edit_svg or has_edit_button

    def _fill_education_entry(self, modal, edu: Education) -> None:
        page = "education"

        school_field = modal.get_by_role("textbox", name="School")
        city_field = modal.get_by_role("textbox", name="City")
        degree_field = modal.get_by_role("textbox", name="Degree")
        major_field = modal.get_by_role("textbox", name="Major / Field of study")
        current_toggle = modal.get_by_text("I currently attend this institution", exact=True)
        start_month_select = modal.locator("select", has_text="Month").first
        end_month_select = modal.locator("select", has_text="Month").nth(1)
        start_year_select = modal.locator("select", has_text="Year").first
        end_year_select = modal.locator("select", has_text="Year").nth(1)

        self._fill_textbox(school_field, edu.institution, page, "school")
        self._fill_textbox(city_field, None, page, "city")  # Education model has no city field -- always skipped
        self._fill_textbox(degree_field, edu.degree, page, "degree")
        self._fill_textbox(major_field, edu.field_of_study, page, "major")

        is_current = edu.end_date is None
        start_month, start_year = parse_month_year(edu.start_date)
        self._select_option(start_month_select, start_month, page, "start_month")
        self._select_option(start_year_select, start_year, page, "start_year")

        if is_current:
            toggled = self._toggle_current_checkbox(current_toggle, page, "currently_attending")
            if toggled:
                return

        end_month, end_year = parse_month_year(edu.end_date)
        self._select_option(end_month_select, end_month, page, "end_month")
        self._select_option(end_year_select, end_year, page, "end_year")

    def _fill_education_page(self, modal, candidate: CandidateProfile):
        page = "education"
        if self._education_already_filled(modal):
            self._log_field(page, "entry", None, status="skipped", note="already pre-filled by LinkedIn (edit indicator present)")
            return

        add_button = modal.get_by_role("button", name=re.compile(r"add education|add formation|ajouter", re.IGNORECASE))
        if add_button.count() == 0:
            self._log_field(page, "entry", None, status="skipped", note="no add button and no pre-filled entry detected")
            return

        for edu in candidate.education:
            if not edu.institution and not edu.degree:
                self._log_field(page, "entry", None, status="skipped", note="education entry has neither institution nor degree")
                continue

            add_button.first.click()
            self.page.wait_for_timeout(800)
            self._fill_education_entry(modal, edu)

            add_button = modal.get_by_role("button", name=re.compile(r"add education|add formation|ajouter", re.IGNORECASE))
            if add_button.count() == 0:
                break

    AUTO_CHECK_PATTERNS = [
        re.compile(r"accept.*terms", re.IGNORECASE),
        re.compile(r"j'accepte", re.IGNORECASE),
        re.compile(r"certify|certifie", re.IGNORECASE),
        re.compile(r"privacy policy|politique de confidentialit[ée]", re.IGNORECASE),
    ]

    def _fill_additional_questions_page(self, modal) -> list[str]:
        """Auto-checks known consent/legal checkboxes and logs each one.
        Returns a list of any other question labels it didn't recognize,
        so the caller can stop and route the job to human review instead
        of guessing at free-text or judgment-requiring answers (salary
        expectations, visa sponsorship, etc)."""
        page = "additional_questions"
        unhandled: list[str] = []

        # checkbox = modal.get_by_role("checkbox")
        # for i in range(checkboxes.count()):
        #     checkbox = checkboxes.nth(i)
        #     label_text = checkbox.locator("xpath=ancestor::label[1] | xpath=..").inner_text()
        #     if any(p.search(label_text) for p in self.AUTO_CHECK_PATTERNS):
        #         if not checkbox.is_checked():
        #             checkbox.check()
        #             self._log_field(page, label_text.strip()[:80], "checked", status="filled")
        #         else:
        #             self._log_field(page, label_text.strip()[:80], "checked", status="already_present")
        #     else:
        #         unhandled.append(label_text.strip())

        modal.get_by_text("J'accepte").first.click()
        text_inputs = modal.locator("input[type='text'], textarea")
        for i in range(text_inputs.count()):
            field = text_inputs.nth(i)
            if field.input_value().strip() == "":
                label = field.get_attribute("aria-label") or "(unlabeled text field)"
                unhandled.append(label)

        if unhandled:
            self._log_field(page, "unhandled_questions", ", ".join(unhandled)[:500], status="warning",
                             note="stopping run for human review")

        return unhandled

    def _click_next_or_submit(self, modal, dry_run: bool) -> str:
        submit_button = modal.get_by_role("button", name=re.compile(r"submit application|envoyer la candidature", re.IGNORECASE))
        if submit_button.count() > 0:
            if dry_run:
                print("[DRY RUN] Reached submit button, not submitting.")
                return "dry_run_stop"
            submit_button.first.click()
            self.page.wait_for_load_state("networkidle")
            return "submitted"

        review_button = modal.get_by_role("button", name=re.compile(r"^review$|^v[ée]rifier$", re.IGNORECASE))
        if review_button.count() > 0:
            review_button.first.click()
            self.page.wait_for_timeout(1200)
            return "continue"

        next_button = modal.get_by_role("button", name=re.compile(r"^\s*(next|suivant)\s*$", re.IGNORECASE))
        if next_button.count() > 0:
            next_button.first.click()
            self.page.wait_for_timeout(1200)
            return "continue"

        raise RuntimeError("No Next/Review/Submit button found -- unknown page state, cannot proceed.")

    # -----------------------------------------------------------------
    # Main entry point
    # -----------------------------------------------------------------

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
        max_pages: int = 15,
    ) -> ApplicationLog:
        self._current_job_url = job_url
        self._current_candidate_id = candidate.candidate_id
        self._current_payload = {}

        self.page.goto(job_url, wait_until="domcontentloaded", timeout=30000)
        locator = self.page.get_by_text("No longer accepting applications", exact=False)
        if locator.count() > 0:
            print(f"Job {job_url} is no longer accepting applications -- marking closed instead of attempting to apply.")
            self._mark_job_closed(raw_job, job_offer)
            log = ApplicationLog(
                job_url=job_url,
                candidate_id=candidate.candidate_id,
                dry_run=True,
                submitted=False,
                payload={"reason": "job_no_longer_accepting_applications"},
                cover_letter_source="none",
            )
            save_application_log(self.applications_output_path, log)
            return log


        easy_apply_btn = self.page.get_by_role("button", name=re.compile(r"LinkedIn Apply to this job", re.IGNORECASE))
        easy_apply_btn.wait_for(state="visible", timeout=10000)
        easy_apply_btn.click()

        modal = self.page.locator("[data-testid='dialog-content']")
        modal.wait_for(state="visible", timeout=10000)

        cover_letter_text = generate_cover_letter(
            candidate=candidate,
            match_result=match_result,
            job_offer=job_offer,
            company=raw_job.company,
            job_description=raw_job.description,
            llm=llm,
        )
        cover_letter_pdf_path = save_cover_letter_as_pdf(
            letter_text=cover_letter_text,
            candidate_name=candidate.personal_information.full_name,
        )

        
        cover_letter_source = "generated" if cover_letter_text else "none"

        for page_index in range(max_pages):
            modal = self.page.locator("[data-testid='dialog-content']")
            modal.wait_for(state="visible", timeout=10000)
            self.sb.sleep(5)
            page_text = modal.inner_text()

            is_personal_info = bool(re.search(r"contact info|coordonn[ée]es", page_text, re.IGNORECASE))
            is_cv = modal.get_by_role("button", name="Upload resume").count() > 0
            is_cover_letter = bool(re.search(r"cover letter|lettre de motivation", page_text, re.IGNORECASE))
            is_experience = bool(re.search(r"work experience|exp[ée]rience professionnelle", page_text, re.IGNORECASE))
            is_education = bool(re.search(r"\bformation\b|\beducation\b", page_text, re.IGNORECASE))
            is_additional_questions = bool(re.search(r"questions suppl[ée]mentaires|additional questions", page_text, re.IGNORECASE))
            is_review = bool(re.search(r"\breview\b|\bv[ée]rifier\b", page_text, re.IGNORECASE))

            if is_personal_info:
                self._fill_personal_info_page(modal, candidate)
            if is_cv:
                self._fill_cv_upload(modal, cv_path)
            if is_cover_letter:
                self._fill_cover_letter_upload(modal, cover_letter_pdf_path)
            if is_experience:
                self._fill_experience_page(modal, candidate)
            if is_education:
                self._fill_education_page(modal, candidate)

            if is_additional_questions:
                unhandled = self._fill_additional_questions_page(modal)
                if unhandled:
                    self._current_payload["unhandled_questions"] = unhandled
                    log = ApplicationLog(
                        job_url=job_url,
                        candidate_id=candidate.candidate_id,
                        dry_run=True,
                        submitted=False,
                        payload=self._current_payload,
                        cover_letter_source=cover_letter_source,
                    )
                    save_application_log(self.applications_output_path, log)
                    return log

            action = self._click_next_or_submit(modal, dry_run)
            if action in ("submitted", "dry_run_stop"):
                submitted = action == "submitted"
                log = ApplicationLog(
                    job_url=job_url,
                    candidate_id=candidate.candidate_id,
                    dry_run=dry_run,
                    submitted=submitted,
                    payload=self._current_payload,
                    cover_letter_source=cover_letter_source,
                )
                save_application_log(self.applications_output_path, log)
                return log

        raise RuntimeError(f"Exceeded max_pages={max_pages} without reaching submit -- possible infinite loop or unrecognized page.")
