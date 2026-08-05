import json
import os
from datetime import date, datetime

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
        cookies = self.page.context.cookies()  
        for c in cookies:
            print(c.get("name"), c.get("expires"))
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
        with open(self.output_file, "r", encoding="utf-8") as f:
            cards = json.load(f)

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

        return existing

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