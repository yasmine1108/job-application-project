import json
import os

from src.scrapers.base_scraper import BaseScraper
from src.models import JobOffer
from config.settings import Settings

class LinkedInScraper(BaseScraper):
    def __init__(self):
        super().__init__(base_url="http://www.linkedin.com/")
        
        self.email = Settings.LINKEDIN_EMAIL
        self.password = Settings.LINKEDIN_PASSWORD
        self.output_file = "data/outputs/linkedin_links.json"
        self.jobs_list_file = "data/outputs/linkedin_job_list.json"

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
                jobs = [JobOffer(**job) if isinstance(job, dict) else job for job in saved_jobs]
            except json.JSONDecodeError:
                jobs = []

        existing_job_urls = {job.job_url for job in jobs if job.job_url}
        new_urls = [u for u in urls_existantes if u not in existing_job_urls]

        for url in new_urls:
            self.sb.sleep(5)
            self.page.goto(url)

            job_offer = self._extract_via_dom()
            job_offer.job_url = url
            jobs.append(job_offer)

        with open(self.jobs_list_file, "w", encoding="utf-8") as f:
            json.dump(
                [job.model_dump() if hasattr(job, "model_dump") else job.dict() for job in jobs],
                f,
                indent=4,
                ensure_ascii=False,
            )

    def _extract_via_dom(self):

        # html = self.page.content()

        # with open("job.html", "w", encoding="utf-8") as f:
        #     f.write(html)

        parts = self.page.title().split(" | ")

        return JobOffer(
            title=parts[0] if parts else "",
            company=self._safe_text(lambda: self.page.locator("a[href*='/company/']").first),
            location=self._safe_text(lambda: self.page.locator("text=/Remote|Hybrid|On-site|(?:[A-ZÀ-ÿ][A-Za-zÀ-ÿ-]+(?:, [A-ZÀ-ÿ][A-Za-zÀ-ÿ-]+)+)/").first),
            description=self._safe_text(lambda: self.page.locator("div:has(h2:text-matches('About the job', 'i')) ~ p").first),
            date_posted=self._safe_text(lambda: self.page.locator(
                r"text=/\b(?:\d+\+?\s+)?(?:hour|day|week|month|year)s?\s+ago\b/i").first),
        )

    def auto_apply(self, job_url, cv_path):
        """Méthode dédiée à l'interaction bouton par bouton (Phase 2)"""
        # Ton code pour ouvrir l'URL d'une offre, cliquer sur postuler et uploader le CV
        pass