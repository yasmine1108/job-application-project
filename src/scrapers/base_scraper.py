from playwright.sync_api import sync_playwright
from seleniumbase import sb_cdp
import os
import shutil

class BaseScraper:
    def __init__(self, base_url, profile_name=None):
        self.base_url = base_url
        self.pw = None
        self.browser = None
        self.page = None
        self.context = None
        self.sb = None

        # One persistent profile per scraper (e.g. "linkedinscraper", "tanitjobsscraper")
        # unless a custom name is passed
        profile_name = profile_name or self.__class__.__name__.lower()
        self.user_data_dir = os.path.join(
            os.path.expanduser("~"), ".scraper_profiles", profile_name
        )
        self.is_new_session = not os.path.exists(self.user_data_dir) or not os.listdir(self.user_data_dir)
        os.makedirs(self.user_data_dir, exist_ok=True)

    def start_browser(self, headless=False, force_new_session=False):
        if force_new_session and os.path.exists(self.user_data_dir):
            shutil.rmtree(self.user_data_dir)
            os.makedirs(self.user_data_dir, exist_ok=True)
            self.is_new_session = True

        self.sb = sb_cdp.Chrome(
            self.base_url,
            locale="en",
            user_data_dir=self.user_data_dir,
            headless=headless,
        )
        endpoint_url = self.sb.get_endpoint_url()
        self.pw = sync_playwright().start()
        self.browser = self.pw.chromium.connect_over_cdp(endpoint_url)
        self.context = self.browser.contexts[0]
        self.page = self.context.pages[0]
        self.sb.sleep(5)

        self.handle_challenge()

    def handle_challenge(self):
        """Solve Cloudflare/other bot-check challenges, only if one is present."""
        if self._challenge_present():
            print("Challenge détecté, résolution en cours...")
            self.sb.solve_captcha()
            self.sb.sleep(3)

    def _challenge_present(self):
        try:
            return self.sb.is_element_visible(
                "iframe[src*='challenges.cloudflare']"
            ) or self.sb.is_element_visible(
                "iframe[src*='captcha'], div#captcha, .cf-turnstile"
            )
        except Exception:
            return False

    def is_logged_in(self):
        """Override in subclasses: return True if the persisted session is already authenticated."""
        raise NotImplementedError

    def ensure_logged_in(self):
        """Login only if there's no valid persisted session."""
        if not self.is_new_session and self.is_logged_in():
            print(f"{self.__class__.__name__}: session existante détectée, login sauté.")
            return
        print(f"{self.__class__.__name__}: pas de session valide, connexion en cours...")
        self.login()

    def login(self):
        raise NotImplementedError

    def close_browser(self):
        self.sb.sleep(5)
        if self.browser:
            self.browser.close()
        if self.pw:
            self.pw.stop()

    def _safe_text(self, locator_fn, timeout=5000):
        try:
            loc = locator_fn()
            loc.wait_for(state="visible", timeout=timeout)
            return loc.inner_text()
        except Exception:
            return ""