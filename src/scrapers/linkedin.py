import json
import os
from datetime import datetime

from src.application_logging import ApplicationLog
from src.llm.fallback import FallbackLLM
from src.matchers.matcher import MatchResult
from src.models import CandidateProfile
from src.scrapers.job_board_scraper import JobBoardScraper
from src.scrapers.base_scraper import BaseScraper
from src.models_job import JobOffer, RawJob
from config.settings import Settings

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
        
        # checkbox = self.page.locator("xpath=/html/body/div[1]/div[2]/div/div/div/main/div/div[2]/div/div[1]/div/div/div[2]/div/div/div/div[2]/div/div[3]/div[5]/div/div/div/p")
        # checkbox.wait_for(state="visible")
        
        signinbutton = self.page.get_by_role("button", name="Sign in", exact=True)
        signinbutton.wait_for(state="visible")
        email_input.fill(self.email)
        password_input.fill(self.password)
        # checkbox.click()
        signinbutton.click()


        print(f"Titre de la page : {self.page.title()}")

    def search_and_collect_links(self, keyword):
        self.sb.sleep(20)
        search_input = self.page.get_by_placeholder("Search")
        search_input.wait_for(state="visible")
        search_input.fill(keyword)
        search_input.press("Enter")
        jobsbuttonvisible = self.page.get_by_role("radio", name="Filter by Jobs")
        # if jobsbuttonvisible.is_visible():
        jobsbuttonvisible.wait_for(state="visible")
        jobsbuttonvisible.click()

        self.sb.sleep(10)
        job_cards = self.page.locator("div[role='button'][componentkey^='job-card-component-ref-']")
        job_cards.first.wait_for(state="visible")

        cards_count = job_cards.count()
        print(f"Nombre de cartes détectées : {cards_count}")

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
        
        # Charger les anciennes URLs si le fichier existe déjà et n'est pas vide
        urls_existantes = []
        if os.path.exists(self.output_file) and os.path.getsize(self.output_file) > 0:
            try:
                with open(self.output_file, "r", encoding="utf-8") as f:
                    urls_existantes = json.load(f)
                print(f"{len(urls_existantes)} anciennes URLs chargées depuis le fichier.")
            except json.JSONDecodeError:
                # Si le fichier est corrompu, on repart sur une liste vide
                urls_existantes = []

        # Fusionner les nouvelles URLs avec les anciennes en évitant les doublons
        compteur_nouveaux = 0
        for url in urls:
            if url not in urls_existantes:
                urls_existantes.append(url)
                compteur_nouveaux += 1

        # Réécrire l'intégralité de la liste mise à jour
        with open(self.output_file, "w", encoding="utf-8") as f:
            json.dump(urls_existantes, f, indent=4, ensure_ascii=False)
            
        print(f"Sauvegarde terminée. Total général : {len(urls_existantes)} URLs ({compteur_nouveaux} ajoutées).")
        return urls


    def extract_job_list(self):
        urls_existantes = []
        jobs = []
        new_urls = []
        if os.path.exists(self.output_file) and os.path.getsize(self.output_file) > 0:
            try:
                with open(self.output_file, "r", encoding="utf-8") as f:
                    urls_existantes = json.load(f)
                print(f"{len(urls_existantes)} anciennes URLs chargées depuis le fichier.")
            except json.JSONDecodeError:
                urls_existantes = []

        if os.path.exists(self.jobs_list_file) and os.path.getsize(self.jobs_list_file) > 0:
            try:
                with open(self.jobs_list_file, "r", encoding="utf-8") as f:
                    saved_jobs = json.load(f)
                jobs = [RawJob(**job) if isinstance(job, dict) else job for job in saved_jobs]
            except json.JSONDecodeError:
                jobs = []

        existing_job_urls = {job.job_url for job in jobs if job.job_url}
        new_urls = [u for u in urls_existantes if u not in existing_job_urls]

        for url in new_urls:
            self.sb.sleep(5)
            self.page.goto(url)

            job_offer = self._extract_via_dom()
            job_offer.job_url = url
            job_offer.job_id = url.split("/")[-2]  # Extract job ID from URL
            locator = self.page.get_by_text(
                "No longer accepting applications",
                exact=False
            )
            if locator.count() > 0:
                job_offer.accepting_applications = False
            
            job_links = self.page.locator(
                f'a[href*="{url}"]'
            )
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
            jobs.append(job_offer)

        serializable_jobs = []
        for job in jobs:
            job_data = job.model_dump() if hasattr(job, "model_dump") else job.dict()
            for key, value in list(job_data.items()):
                if isinstance(value, (datetime,)):
                    job_data[key] = value.isoformat()
            serializable_jobs.append(job_data)

        with open(self.jobs_list_file, "w", encoding="utf-8") as f:
            json.dump(serializable_jobs, f, indent=4, ensure_ascii=False)

        return jobs

    def _extract_via_dom(self):

        # html = self.page.content()

        # with open("job.html", "w", encoding="utf-8") as f:
        #     f.write(html)

        parts = self.page.title().split(" | ")

        return RawJob(
            title=parts[0] if parts else "",
            company=self._safe_text(lambda: self.page.locator("a[href*='/company/']").first),
            location=self._safe_text(lambda: self.page.locator("text=/Remote|Hybrid|On-site|(?:[A-ZÀ-ÿ][A-Za-zÀ-ÿ-]+(?:, [A-ZÀ-ÿ][A-Za-zÀ-ÿ-]+)+)/").first),
            description=self._safe_text(lambda: self.page.locator("div:has(h2:text-matches('About the job', 'i')) ~ p").first),
            date_posted=self._safe_text(lambda: self.page.locator(
                r"text=/\b(?:\d+\+?\s+)?(?:hour|day|week|month|year)s?\s+ago\b/i").first),
        )

    def _fill_typeahead_location(self, location_field, location_text: str) -> bool:
        """LinkedIn's location field only registers a value when a suggestion
        is selected from the dropdown — typing text alone doesn't persist.
        Returns True if a suggestion was successfully selected."""
        if not location_text:
            return False

        location_field.click()
        location_field.press_sequentially(location_text, delay=80)

        # suggestions appear as a listbox after typing; give it a moment to populate
        suggestion = self.page.locator("[role='listbox'] [role='option']").first
        try:
            suggestion.wait_for(state="visible", timeout=5000)
            suggestion.click()
            return True
        except Exception as e:
            print(f"WARNING: no location suggestion appeared for '{location_text}' ({e})")
            return False

    
        
    def auto_apply(self, job_url: str, candidate: CandidateProfile, cv_path: str, llm: FallbackLLM, match_result: MatchResult, job_offer: JobOffer, raw_job: RawJob, dry_run: bool = True,) -> ApplicationLog:
        self.page.goto(job_url, wait_until="domcontentloaded", timeout=30000)
        locator = self.page.get_by_text("No longer accepting applications", exact=False)
        if locator.count() > 0:
            raise NotImplementedError("Job is no longer accepting applications. Auto-apply cannot proceed.")
        easy_apply_btn = self.page.get_by_role("button", name="LinkedIn Apply to this job")
        easy_apply_btn.wait_for(state="visible", timeout=10000)
        easy_apply_btn.click()

        modal = self.page.locator("[data-testid='dialog-content']")
        modal.wait_for(state="visible", timeout=10000)
        self.sb.sleep(5)  # Allow modal content to fully render


        fname_field = modal.get_by_label("First name").or_(self.page.get_by_label("Prénom"))
        lname_field = modal.get_by_label("Last name").or_(self.page.get_by_label("Nom"))
        phone_code_dropdown = modal.get_by_label("Phone country code")
        phone_number_field = modal.locator("input[type='tel']").or_(self.page.get_by_label("Numéro de téléphone portable"))
        email_dropdown = modal.get_by_label("Email address").or_(self.page.get_by_label("Adresse e-mail"))
        location = modal.get_by_placeholder("Enter city or location")

        if fname_field.count() > 0 and fname_field.input_value().strip() == "":
            print(f"Filling first name field with: {candidate.first_name}")
            fname_field.fill(candidate.first_name)
        if lname_field.count() > 0 and lname_field.input_value().strip() == "":
            print(f"Filling last name field with: {candidate.last_name}")
            lname_field.fill(candidate.last_name)
        if phone_code_dropdown.count() > 0 and phone_code_dropdown.input_value().strip() == "":
            print(f"Filling phone country code field with: {candidate.phone_country_code}")
            phone_code_dropdown.select_option(value = candidate.phone_country_code.lower())
        if phone_number_field.count() > 0 and phone_number_field.input_value().strip() == "":
            print(f"Filling phone number field with: {candidate.personal_information.phone}")
            phone_number_field.fill(candidate.personal_information.phone)
        if email_dropdown.count() > 0 and email_dropdown.input_value().strip() == "":
            print(f"Filling email field with: {candidate.personal_information.email}")
            email_dropdown.select_option(value = candidate.personal_information.email)
        if location.count() > 0 and location.input_value().strip() == "":
            print(f"Filling location field with: {candidate.personal_information.location}")
            self._fill_typeahead_location(location, candidate.personal_information.location)

        print({
            "first_name": fname_field.input_value() if fname_field.count() > 0 else None,
            "last_name": lname_field.input_value() if lname_field.count() > 0 else None,
            "phone_country_code": phone_code_dropdown.input_value() if phone_code_dropdown.count() > 0 else None,
            "phone_number": phone_number_field.input_value() if phone_number_field.count() > 0 else None,
            "email": email_dropdown.input_value() if email_dropdown.count() > 0 else None,
            "location": location.input_value() if location.count() > 0 else None
        })

        # Selects the span containing the exact text "Next"
        next_button = self.page.get_by_text("Next", exact=True)
        next_button.click()

        self.sb.sleep(5)  # Allow next step to load
        hidden_inputs = modal.locator("input[type='file']")
        print(f"Hidden file inputs found: {hidden_inputs.count()}")