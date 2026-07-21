from src.scrapers.base_scraper import BaseScraper
from config.settings import Settings

class TanitJobsScraper(BaseScraper):
    def __init__(self):
        super().__init__(base_url="http://www.tanitjobs.com/")
        
        self.email = Settings.LINKEDIN_EMAIL
        self.password = Settings.LINKEDIN_PASSWORD
    
    def login(self):
        
        cnx_btn = self.page.locator("xpath=/html/body/nav/div/div[4]/ul/li[1]/a")
        cnx_btn.wait_for(state="visible")
        cnx_btn.click()
        self.page.locator("xpath=/html/body/div[4]/div/div[1]/div[1]/div/form/div[1]/input").fill(self.email)
        self.page.locator("xpath=/html/body/div[4]/div/div[1]/div[1]/div/form/div[2]/input").fill(self.password)
        self.page.locator("xpath=/html/body/div[4]/div/div[1]/div[1]/div/form/table/tbody/tr/td[1]/div/input").click()
        self.sb.sleep(5)