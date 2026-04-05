"""MediaWiki API client for bot operations (login, upload, page queries)."""

import re
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

    def get_all_pages(self, namespace: int = 0) -> list[str]:
        """Get all pages in a namespace."""
        pages = []
        params = {
            "action": "query", "list": "allpages",
            "apnamespace": str(namespace), "aplimit": "500",
            "format": "json",
        }
        while True:
            resp = self.session.get(self.api_url, params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            for page in data["query"]["allpages"]:
                pages.append(page["title"])
            if "continue" in data:
                params["apcontinue"] = data["continue"]["apcontinue"]
            else:
                break
        return pages

    def page_has_text(self, page_title: str, search_text: str) -> bool:
        """Check if a page's raw wikitext contains a string."""
        resp = self.session.get(self.api_url, params={
            "action": "query", "titles": page_title,
            "prop": "revisions", "rvprop": "content",
            "rvslots": "main", "format": "json",
        }, timeout=30)
        resp.raise_for_status()
        pages = resp.json()["query"]["pages"]
        page = next(iter(pages.values()))
        if "revisions" not in page:
            return False
        content = page["revisions"][0]["slots"]["main"]["*"]
        return search_text in content

    def get_page_revisions(self, titles: list[str]) -> dict[str, str | None]:
        """Batch-fetch current revision IDs for multiple pages."""
        results = {t: None for t in titles}
        for i in range(0, len(titles), 50):
            batch = titles[i:i+50]
            resp = self.session.get(self.api_url, params={
                "action": "query", "titles": "|".join(batch),
                "prop": "revisions", "rvprop": "ids",
                "format": "json",
            }, timeout=30)
            resp.raise_for_status()
            for page in resp.json()["query"]["pages"].values():
                title = page.get("title", "")
                if "revisions" in page:
                    results[title] = str(page["revisions"][0]["revid"])
        return results

    def get_file_revisions(self, filenames: list[str]) -> dict[str, str | None]:
        """Batch-fetch source revision IDs from upload comments of multiple files."""
        results = {f: None for f in filenames}
        # Build a lookup: normalized name -> original filename
        norm_lookup = {f.replace("_", " "): f for f in filenames}
        titles = [f"File:{f}" for f in filenames]
        for i in range(0, len(titles), 50):
            batch = titles[i:i+50]
            resp = self.session.get(self.api_url, params={
                "action": "query", "titles": "|".join(batch),
                "prop": "imageinfo", "iiprop": "comment",
                "format": "json",
            }, timeout=30)
            resp.raise_for_status()
            for page in resp.json()["query"]["pages"].values():
                title = page.get("title", "")
                # Strip namespace prefix (File: / Файл:) and match back
                fname = title.split(":", 1)[-1] if ":" in title else title
                original = norm_lookup.get(fname) or norm_lookup.get(fname.replace(" ", "_"))
                if original and "imageinfo" in page:
                    comment = page["imageinfo"][0].get("comment", "")
                    m = re.search(r"Auto-generated from revision (\d+)", comment)
                    if m:
                        results[original] = m.group(1)
        return results

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
