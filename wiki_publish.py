#!/usr/bin/env python3
"""Query wiki for pages with {{Wbincludes:pdf}}, generate PDFs, upload to wiki."""

import argparse
import sys
import time

from lib.wiki_api import WikiBot
from wiki2pdf import generate_pdf, BASE_URL

BOT_USER = "EvgenyBoger@PdfUploader"
BOT_PASS = "b0p67f45pf4gl4k2uq0eh8fgebre58ks"

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
    args = parser.parse_args()

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
        print("Querying pages with {{Wbpdf}}...", file=sys.stderr)
        pages = bot.get_pages_with_template("Template:Wbpdf")
        if not pages:
            # Fallback: embeddedin may be stale if wiki job queue isn't running.
            # Use grep-style search on wikitext via API.
            print("  embeddedin empty, trying search...", file=sys.stderr)
            for term in ["Wbpdf", "Wbincludes:pdf"]:
                resp = bot.session.get(bot.api_url, params={
                    "action": "query", "list": "search",
                    "srsearch": f'insource:"{{{{{term}}}}}"',
                    "srnamespace": "0", "srlimit": "500", "format": "json",
                }, timeout=30)
                for r in resp.json()["query"]["search"]:
                    if r["title"] not in pages:
                        pages.append(r["title"])
        print(f"Found {len(pages)} pages.", file=sys.stderr)

    if not pages:
        print("No pages found.", file=sys.stderr)
        return

    if args.dry_run:
        for page in pages:
            print(f"  {page}")
        return

    success = []
    failed = []

    for i, page in enumerate(pages):
        print(f"\n[{i+1}/{len(pages)}] {page}", file=sys.stderr, flush=True)
        url = f"{BASE_URL}/wiki/{page}"
        t0 = time.time()
        try:
            pdf_path = generate_pdf(url, keep_typst=args.keep_typst)
            elapsed = time.time() - t0
            print(f"  Generated ({elapsed:.1f}s)", file=sys.stderr)

            if not args.no_upload:
                upload_name = f"{page}_manual.pdf"
                print(f"  Uploading as {upload_name}...", file=sys.stderr)
                bot.upload_file(upload_name, pdf_path,
                                comment="Auto-generated PDF manual")
                print(f"  Uploaded.", file=sys.stderr)

            success.append(page)
        except Exception as e:
            elapsed = time.time() - t0
            err = str(e).split("\n")[0][:100]
            print(f"  FAILED ({elapsed:.1f}s): {err}", file=sys.stderr)
            failed.append((page, err))

    print(f"\n=== Results: {len(success)} OK, {len(failed)} failed ===",
          file=sys.stderr)
    for page, err in failed:
        print(f"  FAIL: {page}: {err}", file=sys.stderr)


if __name__ == "__main__":
    main()
