#!/usr/bin/env python3
"""Query wiki for pages with {{Wbincludes:pdf}}, generate PDFs, upload to wiki."""

import argparse
import os
import sys
import time

from lib.wiki_api import WikiBot
from wiki2pdf import generate_pdf, BASE_URL

BOT_USER = os.environ.get("WIKI_BOT_USER", "")
BOT_PASS = os.environ.get("WIKI_BOT_PASS", "")


def sanitize_filename(page_name: str) -> str:
    """Convert a wiki page name to a safe upload filename, matching MediaWiki's sanitization."""
    return page_name.replace("/", "-") + "_manual.pdf"

TEMPLATE_TITLE = "Wbincludes:pdf"
TEMPLATE_WIKITEXT = """\
<div class="pdf-download noprint" style="background:#f0f7ff; border:1px solid #c0d8f0; border-radius:4px; padding:8px 12px; margin:8px 0;">
&#x1F4CB; '''[[Media:{{PAGENAME}}_manual.pdf|Скачать PDF-версию руководства]]'''
</div>"""


def main():
    parser = argparse.ArgumentParser(
        description="Generate and upload PDF manuals for wiki pages with {{Wbincludes:pdf}}"
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="List pages, don't generate or upload")
    parser.add_argument("--no-upload", action="store_true",
                        help="Generate PDFs but skip upload")
    parser.add_argument("--page", help="Process only this page name")
    parser.add_argument("--keep-typst", action="store_true",
                        help="Keep intermediate .typ files")
    parser.add_argument("--setup", action="store_true",
                        help="Create the Wbincludes:pdf template on the wiki")
    parser.add_argument("--pages-from", metavar="FILE",
                        help="Read page names from file (one per line) instead of querying wiki")
    parser.add_argument("--force", action="store_true",
                        help="Regenerate even if PDF is up to date")
    args = parser.parse_args()

    if not BOT_USER or not BOT_PASS:
        print("Error: set WIKI_BOT_USER and WIKI_BOT_PASS environment variables", file=sys.stderr)
        sys.exit(1)

    bot = WikiBot()
    print("Logging in...", file=sys.stderr)
    bot.login(BOT_USER, BOT_PASS)
    print("Logged in.", file=sys.stderr)

    if args.setup:
        print("Creating template...", file=sys.stderr)
        bot.edit_page(TEMPLATE_TITLE, TEMPLATE_WIKITEXT,
                      summary="Create PDF download template")
        print(f"Template {TEMPLATE_TITLE} created.", file=sys.stderr)
        return

    # Get page list
    if args.page:
        pages = [args.page]
    elif args.pages_from:
        with open(args.pages_from) as f:
            pages = [line.strip() for line in f if line.strip()]
        print(f"Read {len(pages)} pages from {args.pages_from}.", file=sys.stderr)
    else:
        print("Querying pages with {{Wbincludes:pdf}}...", file=sys.stderr)
        pages = bot.get_pages_with_template(TEMPLATE_TITLE)
        if not pages:
            # Fallback: embeddedin may be stale if wiki job queue isn't running.
            # Use grep-style search on wikitext via API.
            print("  embeddedin empty, trying search...", file=sys.stderr)
            resp = bot.session.get(bot.api_url, params={
                "action": "query", "list": "search",
                "srsearch": 'insource:"{{Wbincludes:pdf}}"',
                "srnamespace": "0", "srlimit": "500", "format": "json",
            }, timeout=30)
            for r in resp.json()["query"]["search"]:
                if r["title"] not in pages:
                    pages.append(r["title"])
        # Filter to main namespace (exclude template/special pages)
        _WIKI_NS = {"Talk", "User", "File", "Template", "Category", "Help",
                     "MediaWiki", "Special", "Wbincludes", "Wbtables",
                     "Участник", "Файл", "Шаблон", "Категория", "Служебная"}
        pages = [p for p in pages
                 if ":" not in p or p.split(":", 1)[0] not in _WIKI_NS]
        print(f"Found {len(pages)} pages.", file=sys.stderr)

    if not pages:
        print("No pages found.", file=sys.stderr)
        return

    if args.dry_run:
        for page in pages:
            print(f"  {page}")
        return

    # Batch-fetch revisions for staleness check
    page_revs = {}
    pdf_revs = {}
    if not args.force and not args.no_upload:
        print("Checking for updates...", file=sys.stderr)
        page_revs = bot.get_page_revisions(pages)
        pdf_revs = bot.get_file_revisions([sanitize_filename(p) for p in pages])

    success = []
    skipped = []
    failed = []

    for i, page in enumerate(pages):
        print(f"\n[{i+1}/{len(pages)}] {page}", file=sys.stderr, flush=True)

        # Check if PDF is already up to date
        if not args.force and not args.no_upload:
            current_rev = page_revs.get(page)
            pdf_rev = pdf_revs.get(sanitize_filename(page))
            if current_rev and pdf_rev and current_rev == pdf_rev:
                print(f"  Up to date (rev {current_rev})", file=sys.stderr)
                skipped.append(page)
                continue

        url = f"{BASE_URL}/wiki/{page}"
        t0 = time.time()
        try:
            pdf_path, revid = generate_pdf(url, keep_typst=args.keep_typst)
            elapsed = time.time() - t0
            print(f"  Generated ({elapsed:.1f}s)", file=sys.stderr)

            if not args.no_upload:
                upload_name = sanitize_filename(page)
                print(f"  Uploading as {upload_name}...", file=sys.stderr)
                comment = (f"Auto-generated from revision {revid}. "
                           f"https://github.com/wirenboard/wiki-pdf-typst")
                bot.upload_file(upload_name, pdf_path, comment=comment)
                print(f"  Uploaded.", file=sys.stderr)

            success.append(page)
        except Exception as e:
            elapsed = time.time() - t0
            err = str(e).split("\n")[0][:100]
            print(f"  FAILED ({elapsed:.1f}s): {err}", file=sys.stderr)
            failed.append((page, err))

    print(f"\n=== Results: {len(success)} updated, {len(skipped)} up-to-date, {len(failed)} failed ===",
          file=sys.stderr)
    for page, err in failed:
        print(f"  FAIL: {page}: {err}", file=sys.stderr)

    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
