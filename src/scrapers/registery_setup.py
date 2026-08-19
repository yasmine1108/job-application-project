from src.scrapers.job_board_scraper import register_scraper
from src.scrapers.tanitjobs import TanitJobsScraper
from src.scrapers.linkedin import LinkedInScraper

register_scraper("tanitjobs.com", TanitJobsScraper)
register_scraper("linkedin.com", LinkedInScraper)