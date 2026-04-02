"""Wiki API client and image downloader."""

import hashlib
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urljoin, unquote, urlparse, parse_qs

from bs4 import BeautifulSoup
import requests
import urllib3

# Suppress SSL warnings for environments with self-signed or missing CA certs
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Set to False to skip SSL verification (e.g. missing CA certs in container)
VERIFY_SSL = False

# MediaWiki namespace prefixes to skip when detecting internal wiki links
_SKIP_PREFIXES = ("Special:", "Файл:", "File:", "User:", "Участник:",
                  "Category:", "Категория:", "Template:", "Шаблон:")


def fetch_page(base_url: str, page_name: str) -> dict:
    """Fetch parsed HTML, display title, and revision info from MediaWiki API.

    Returns dict with keys: html, title, revid, revtimestamp.
    """
    api_url = f"{base_url}/wiki/api.php"
    params = {
        "action": "parse",
        "page": page_name,
        "prop": "text|displaytitle|revid",
        "format": "json",
        "redirects": 1,
    }
    resp = requests.get(api_url, params=params, timeout=30, verify=VERIFY_SSL)
    resp.raise_for_status()
    data = resp.json()

    if "error" in data:
        raise RuntimeError(f"MediaWiki API error: {data['error']['info']}")

    html = data["parse"]["text"]["*"]
    title = data["parse"]["displaytitle"]
    title = re.sub(r"<[^>]+>", "", title)
    revid = data["parse"].get("revid", "")

    # Fetch revision timestamp
    revtimestamp = ""
    if revid:
        params2 = {
            "action": "query",
            "revids": revid,
            "prop": "revisions",
            "rvprop": "timestamp",
            "format": "json",
        }
        resp2 = requests.get(api_url, params=params2, timeout=15, verify=VERIFY_SSL)
        if resp2.ok:
            pages = resp2.json().get("query", {}).get("pages", {})
            for page_data in pages.values():
                revs = page_data.get("revisions", [])
                if revs:
                    revtimestamp = revs[0].get("timestamp", "")

    return {"html": html, "title": title, "revid": revid, "revtimestamp": revtimestamp}


def inline_link_sections(html: str, base_url: str) -> str:
    """Replace sections that only contain a link to another wiki page
    with the content of that page."""
    soup = BeautifulSoup(html, "html.parser")
    changed = False
    inlined_pages = set()

    for heading in soup.find_all(["h2", "h3"]):
        # Collect content nodes until next heading of same or higher level
        content_nodes = []
        sib = heading.next_sibling
        while sib:
            if hasattr(sib, "name") and sib.name in ("h2", "h3") and int(sib.name[1]) <= int(heading.name[1]):
                break
            if hasattr(sib, "name") and sib.name:
                content_nodes.append(sib)
            sib = sib.next_sibling

        # Check if section is just a single link to a wiki page
        if not content_nodes:
            continue
        text = " ".join(n.get_text().strip() for n in content_nodes).strip()
        if len(text) > 200:
            continue

        links = []
        for n in content_nodes:
            if hasattr(n, "find_all"):
                for a in n.find_all("a"):
                    href = a.get("href", "")
                    if href.startswith("/wiki/") and "action=" not in href and not any(href.split("/wiki/", 1)[-1].startswith(p) for p in _SKIP_PREFIXES):
                        links.append(href)

        if len(links) != 1:
            continue
        # This section has exactly one internal wiki link — inline it
        linked_page = links[0].split("/wiki/", 1)[-1]
        print(f"  Inlining: {linked_page}", flush=True)
        try:
            page_data = fetch_page(base_url, linked_page)
            sub_html = page_data["html"]
        except Exception as e:
            print(f"  Warning: failed to fetch {linked_page}: {e}", flush=True)
            continue

        # Parse the sub-page content
        sub_soup = BeautifulSoup(sub_html, "html.parser")
        sub_content = sub_soup.find("div", class_="mw-parser-output")
        if not sub_content:
            continue

        # Remove the original link paragraph(s) and insert sub-page content
        for n in content_nodes:
            n.decompose()

        # Remove back-link paragraphs: short <p> with just a wiki link
        # (e.g. "Перейти на страницу устройства", "Документация ... по ссылке")
        for p in list(sub_content.find_all("p")):
            p_links = [a for a in p.find_all("a")
                       if (a.get("href", "") or "").startswith("/wiki/")
                       and "action=" not in (a.get("href", "") or "")]
            if not p_links:
                continue
            text = p.get_text().strip()
            # If paragraph is short and dominated by the link, it's a back-link
            if len(text) < 120:
                link_text = " ".join(a.get_text().strip() for a in p_links)
                if len(link_text) > len(text) * 0.4:
                    p.decompose()

        # Demote headings in sub-content so they nest under the parent heading.
        # E.g. parent is <h2>: sub-content's top-level headings become <h3>.
        sub_headings = sub_content.find_all(["h1", "h2", "h3", "h4", "h5"])
        if sub_headings:
            min_sub_level = min(int(h.name[1]) for h in sub_headings)
            parent_level = int(heading.name[1])
            # Target: top-level sub-headings should be parent_level + 1
            offset = (parent_level + 1) - min_sub_level
            for h_tag in sub_headings:
                level = int(h_tag.name[1])
                new_level = min(max(level + offset, 1), 6)
                h_tag.name = f"h{new_level}"

        # Insert sub-content children after the heading
        insert_after = heading
        for child in list(sub_content.children):
            insert_after.insert_after(child)
            insert_after = child
        inlined_pages.add(linked_page)
        changed = True

    if changed:
        # Rewrite links to inlined pages into local anchor links
        for a in soup.find_all("a"):
            href = a.get("href", "") or ""
            for page in inlined_pages:
                if f"/wiki/{page}" in href:
                    if "#" in href:
                        fragment = href.split("#", 1)[1]
                        a["href"] = f"#{fragment}"
                    else:
                        a.replace_with(a.get_text())
                    break
        return str(soup)
    return html


def download_images(html: str, base_url: str, output_dir: str) -> tuple[dict[str, str], dict[str, list[str]]]:
    """Download all content images from the HTML.

    Returns a mapping of original src URL -> relative file path for Typst.
    """
    soup = BeautifulSoup(html, "html.parser")
    images_dir = os.path.join(output_dir, "images")
    os.makedirs(images_dir, exist_ok=True)

    # Collect download tasks
    tasks = []
    image_map = {}
    for img in soup.find_all("img"):
        src = img.get("src", "")
        if not src:
            continue
        if any(skip in src for skip in ("/resources/", "/skins/", "Special:")):
            continue
        width = img.get("width")
        if width and str(width).isdigit() and int(width) < 20:
            continue

        full_url = urljoin(base_url, src)
        full_res_url = _get_full_res_url(full_url)
        url_hash = hashlib.md5(full_url.encode()).hexdigest()[:12]
        ext = _get_extension(src)
        local_name = f"{url_hash}{ext}"
        local_path = os.path.join(images_dir, local_name)
        relative_path = os.path.join("images", local_name)
        if os.path.exists(local_path):
            image_map[src] = relative_path
            continue

        tasks.append((src, full_res_url, full_url, local_path, relative_path))

    # Download in parallel
    if tasks:
        with ThreadPoolExecutor(max_workers=8) as pool:
            futures = {
                pool.submit(_download_one, full_res, full, local): (src_key, rel)
                for src_key, full_res, full, local, rel in tasks
            }
            for future in as_completed(futures):
                src_key, rel = futures[future]
                if future.result():
                    image_map[src_key] = rel
                else:
                    print(f"  Warning: failed to download {src_key}", flush=True)

    # Post-process GIF files: extract diverse frames
    gif_frames = {}  # src -> list of relative frame paths
    for src, rel_path in list(image_map.items()):
        if rel_path.lower().endswith(".gif"):
            abs_path = os.path.join(output_dir, rel_path)
            frames = _extract_gif_frames(abs_path, images_dir)
            if frames:
                gif_frames[src] = [os.path.join("images", os.path.basename(f)) for f in frames]

    return image_map, gif_frames


def _extract_gif_frames(gif_path: str, output_dir: str, max_frames: int = 8) -> list[str]:
    """Extract up to max_frames visually diverse frames from an animated GIF.

    Returns list of saved PNG file paths, or empty list if not animated.
    """
    try:
        from PIL import Image
    except ImportError:
        return []

    try:
        img = Image.open(gif_path)
        n_frames = getattr(img, "n_frames", 1)
        if n_frames <= 1:
            return []

        # Extract all frames as RGBA arrays
        all_frames = []
        for i in range(n_frames):
            img.seek(i)
            frame = img.convert("RGBA")
            all_frames.append(frame)

        if len(all_frames) <= max_frames:
            selected = all_frames
        else:
            # Select frames with maximum visual diversity using greedy farthest-point
            def frame_diff(a, b):
                arr_a = bytearray(a.tobytes())
                arr_b = bytearray(b.tobytes())
                # Sample pixels for speed (every 100th byte)
                diff = sum(abs(arr_a[i] - arr_b[i]) for i in range(0, min(len(arr_a), len(arr_b)), 100))
                return diff

            selected = [all_frames[0]]
            remaining = list(range(1, len(all_frames)))

            while len(selected) < max_frames and remaining:
                best_idx = 0
                best_min_dist = -1
                for j, r_idx in enumerate(remaining):
                    min_dist = min(frame_diff(all_frames[r_idx], s) for s in selected)
                    if min_dist > best_min_dist:
                        best_min_dist = min_dist
                        best_idx = j
                selected.append(all_frames[remaining.pop(best_idx)])

        # Save selected frames as PNGs
        base = os.path.splitext(os.path.basename(gif_path))[0]
        paths = []
        for i, frame in enumerate(selected):
            frame_path = os.path.join(output_dir, f"{base}_frame{i}.png")
            frame.convert("RGB").save(frame_path)
            paths.append(frame_path)
        return paths
    except Exception as e:
        print(f"  Warning: GIF frame extraction failed for {gif_path}: {e}", flush=True)
        return []


def _download_one(
    full_res_url: str | None,
    full_url: str,
    local_path: str,
) -> bool:
    """Download a single image. Returns True on success."""
    for url in (full_res_url, full_url):
        if url is None:
            continue
        try:
            resp = requests.get(url, timeout=15, verify=VERIFY_SSL)
            if resp.status_code == 200 and len(resp.content) > 100:
                with open(local_path, "wb") as f:
                    f.write(resp.content)
                return True
        except requests.RequestException:
            continue
    return False


def _get_full_res_url(thumb_url: str) -> str | None:
    """Convert a thumbnail URL to full-resolution URL."""
    match = re.search(r"(/wiki/images/)thumb/(.+?)/\d+px-[^/]+$", thumb_url)
    if match:
        return thumb_url[: match.start()] + match.group(1) + match.group(2)
    return None


def _get_extension(url: str) -> str:
    """Extract file extension from URL."""
    path = url.split("?")[0]
    basename = path.rsplit("/", 1)[-1]
    if "." in basename:
        ext = "." + basename.rsplit(".", 1)[-1].lower()
        if ext in (".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp"):
            return ext
    return ".png"


def extract_page_name(url: str) -> tuple[str, str]:
    """Extract page name and base URL from a wiki URL.

    Handles:
      - https://wiki.wirenboard.com/wiki/PageName
      - https://wiki.wirenboard.com/wiki/index.php/PageName
      - https://wiki.wirenboard.com/wiki/index.php?title=PageName

    Returns (base_url, page_name).
    """
    parsed = urlparse(url)
    base_url = f"{parsed.scheme}://{parsed.netloc}"

    qs = parse_qs(parsed.query)
    if "title" in qs:
        return base_url, qs["title"][0]

    path = unquote(parsed.path)
    if "/wiki/index.php/" in path:
        page_name = path.split("/wiki/index.php/", 1)[1]
    elif "/wiki/" in path:
        page_name = path.split("/wiki/", 1)[1]
    else:
        page_name = path.rsplit("/", 1)[-1]

    return base_url, page_name
