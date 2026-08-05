import json
import os

from src.scrapers.base_scraper import BaseScraper
from config.settings import Settings

class TanitJobsScraper(BaseScraper):
    def __init__(self):
        super().__init__(base_url="http://www.tanitjobs.com/")
        
        self.email = Settings.LINKEDIN_EMAIL
        self.password = Settings.LINKEDIN_PASSWORD
        self.output_file = "data/outputs/tanitjobs_links.json"
    
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
        cookies = self.sb.get_all_cookies()  # or self.page.context.cookies() via Playwright
        for c in cookies:
            print(c.get("name"), c.get("expires"))
        self.sb.sleep(5)

    def search_and_collect_links(self, keyword):
        logo_link = self.page.locator("a[href='https://www.tanitjobs.com']")
        logo_link.wait_for(state="visible")
        logo_link.click()
        search_input = self.page.get_by_placeholder("Mots Clés")
        search_input.wait_for(state="visible")
        search_input.fill(keyword)
        search_input.press("Enter")

        self.sb.sleep(5)
        job_cards = self.page.locator(".sj-job-card")
        count = job_cards.count()
        print(f"Nombre de cartes détectées : {count}")

        collected = []
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
            employment_type = self._safe_text(lambda: card.locator("span.sj-type").first)
            date_posted = self._safe_text(lambda: card.locator("span.sj-card-date").first)

            collected.append({
                "job_id": job_id,
                "job_url": job_url,
                "title": title,
                "company": company,
                "location": location,
                "employment_type": employment_type,
                "date_posted": date_posted,
            })

        print(f"Total de cartes collectées : {len(collected)}")
        self._merge_and_save(collected)
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

    def extract_job_list(self):
        """Extract job details from the collected job links and save them to a JSON file."""
        if not os.path.exists(self.output_file) or os.path.getsize(self.output_file) == 0:
            print("No job links found. Please run search_and_collect_links first.")
            return []

        with open(self.output_file, "r", encoding="utf-8") as f:
            job_links = json.load(f)

        jobs = []
        for link in job_links:
            self.sb.sleep(5)
            self.page.goto(link["job_url"])

            job_offer = self._extract_via_dom()
            job_offer.job_url = link["job_url"]
            job_offer.job_id = link["job_id"]
            locator = self.page.get_by_text(
                "No longer accepting applications",
                exact=False
            )
            if locator.count() > 0:
                job_offer.accepting_applications = False

            jobs.append(job_offer.model_dump())

        jobs_output_file = "data/outputs/tanitjobs_raw_job_list.json"
        os.makedirs(os.path.dirname(jobs_output_file), exist_ok=True)
        with open(jobs_output_file, "w", encoding="utf-8") as f:
            json.dump(jobs, f, indent=4, ensure_ascii=False)

        print(f"Extraction terminée. Total de jobs extraits : {len(jobs)}")
        return jobs