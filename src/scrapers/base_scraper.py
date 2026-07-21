from playwright.sync_api import sync_playwright
from seleniumbase import sb_cdp

class BaseScraper:
    def __init__(self, base_url):
        self.base_url = base_url
        self.pw = None
        self.browser = None
        self.page = None
        self.context = None
        self.sb = None

    def start_browser(self):
        self.sb = sb_cdp.Chrome(locale="en")
        endpoint_url = self.sb.get_endpoint_url()
        self.pw = sync_playwright().start()
        self.browser = self.pw.chromium.connect_over_cdp(endpoint_url)
        self.context = self.browser.contexts[0]
        self.page = self.context.pages[0]
        self.page.goto(self.base_url)
        self.sb.sleep(5)
        self.sb.solve_captcha()

    def close_browser(self):
        self.sb.sleep(5)
        if self.browser:
            self.browser.close()
        if self.pw:
            self.pw.stop()