"""MediaWiki API client for bot operations (login, upload, page queries)."""

import requests
from lib.fetcher import VERIFY_SSL

DEFAULT_API_URL = "https://wiki.wirenboard.com/wiki/api.php"


class WikiBot:
    """Authenticated MediaWiki bot session."""

    def __init__(self, api_url: str = DEFAULT_API_URL):
        self.api_url = api_url
        self.session = requests.Session()
        self.session.verify = VERIFY_SSL

    def login(self, username: str, password: str):
        """Two-step MediaWiki bot login."""
        # Step 1: get login token
        resp = self.session.get(self.api_url, params={
            "action": "query", "meta": "tokens",
            "type": "login", "format": "json",
        }, timeout=15)
        resp.raise_for_status()
        token = resp.json()["query"]["tokens"]["logintoken"]

        # Step 2: login with token
        resp = self.session.post(self.api_url, data={
            "action": "login", "lgname": username, "lgpassword": password,
            "lgtoken": token, "format": "json",
        }, timeout=15)
        resp.raise_for_status()
        result = resp.json()["login"]["result"]
        if result != "Success":
            raise RuntimeError(f"Login failed: {result}")

    def get_csrf_token(self) -> str:
        """Get a CSRF token for write operations."""
        resp = self.session.get(self.api_url, params={
            "action": "query", "meta": "tokens",
            "type": "csrf", "format": "json",
        }, timeout=15)
        resp.raise_for_status()
        return resp.json()["query"]["tokens"]["csrftoken"]

    def get_pages_with_template(self, template_title: str) -> list[str]:
        """Query all pages transcluding a given template."""
        pages = []
        params = {
            "action": "query", "list": "embeddedin",
            "eititle": template_title, "eilimit": "500",
            "format": "json",
        }
        while True:
            resp = self.session.get(self.api_url, params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            for page in data["query"]["embeddedin"]:
                pages.append(page["title"])
            if "continue" in data:
                params["eicontinue"] = data["continue"]["eicontinue"]
            else:
                break
        return pages

    def upload_file(self, filename: str, file_path: str, comment: str = "") -> dict:
        """Upload a file to the wiki."""
        token = self.get_csrf_token()
        with open(file_path, "rb") as f:
            resp = self.session.post(self.api_url, data={
                "action": "upload", "filename": filename,
                "comment": comment or "Auto-generated PDF manual",
                "ignorewarnings": "1", "format": "json",
                "token": token,
            }, files={"file": (filename, f)}, timeout=120)
        resp.raise_for_status()
        data = resp.json()
        if "error" in data:
            raise RuntimeError(f"Upload failed: {data['error']['info']}")
        return data

    def edit_page(self, title: str, text: str, summary: str = "") -> dict:
        """Create or edit a wiki page."""
        token = self.get_csrf_token()
        resp = self.session.post(self.api_url, data={
            "action": "edit", "title": title,
            "text": text, "summary": summary or "Auto-created",
            "format": "json", "token": token,
        }, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        if "error" in data:
            raise RuntimeError(f"Edit failed: {data['error']['info']}")
        return data
