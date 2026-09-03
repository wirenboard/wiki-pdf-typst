#!/usr/bin/env python3
"""Query wiki for pages with {{Wbincludes:pdf}}, generate PDFs, upload to wiki."""

import argparse
import hashlib
import os
import sys
import time

from lib.wiki_api import WikiBot, upload_is_no_change
from wiki2pdf import generate_pdf, BASE_URL

BOT_USER = os.environ.get("WIKI_BOT_USER", "")
BOT_PASS = os.environ.get("WIKI_BOT_PASS", "")


def sanitize_filename(page_name: str) -> str:
    """Convert a wiki page name to a safe upload filename, matching MediaWiki's sanitization."""
    # MediaWiki maps every $wgIllegalFileChars (":/\\" by default) to "-" on
    # upload; mirror it, or the staleness lookup misses the stored file and the
    # page is regenerated and re-uploaded on every run.
    for char in ":/\\":
        page_name = page_name.replace(char, "-")
    return page_name + "_manual.pdf"

TEMPLATE_TITLE = "Wbincludes:pdf"
# A bootstrap stub for a fresh wiki, not a copy of the live template: the one on
# wiki.wirenboard.com has since grown an icon, translation markup and its own
# documentation. --setup will not overwrite an existing page for that reason.
# The link has to be built exactly the way sanitize_filename() builds the upload
# name, or the download button points at a file that was never stored.
TEMPLATE_WIKITEXT = """\
<includeonly><div class="pdf-download noprint" style="background:#f0f7ff; border:1px solid #c0d8f0; border-radius:4px; padding:8px 12px; margin:8px 0;">
&#x1F4CB; '''[[Media:{{#replace:{{#replace:{{PAGENAME}}|:|-}}|/|-}}_manual.pdf|Скачать PDF-версию руководства]]'''
</div></includeonly>"""


def file_sha1(path: str) -> str:
    """SHA-1 of a file's contents, in the same hex form the wiki reports for uploads."""
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


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
                        help="Create the Wbincludes:pdf template on a fresh wiki; "
                             "refuses to overwrite an existing one")
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
        try:
            bot.edit_page(TEMPLATE_TITLE, TEMPLATE_WIKITEXT,
                          summary="Create PDF download template",
                          createonly=True)
        except RuntimeError as e:
            sys.exit(f"{e}\n{TEMPLATE_TITLE} already exists. Edit it on the wiki "
                     f"instead; the text in this script is a bootstrap stub, not "
                     f"a copy of what is live.")
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
        # The Translate extension serves Page/<content language> as a 301 to
        # Page — for the source language the subpage is not something a reader
        # can land on, and its PDF is a byte-for-byte second copy of the base
        # one. Real translations (Page/en) redirect nowhere and are kept.
        source_suffix = "/" + bot.get_content_language()
        pages = [p for p in pages if not p.endswith(source_suffix)]
        print(f"Found {len(pages)} pages.", file=sys.stderr)

    if not pages:
        print("No pages found.", file=sys.stderr)
        return

    if args.dry_run:
        for page in pages:
            print(f"  {page}")
        return

    # Batch-fetch what the wiki already holds, for the staleness and content checks
    page_revs = {}
    file_state = {}
    if not args.no_upload:
        print("Checking for updates...", file=sys.stderr)
        # Output is reproducible, so a PDF matching the stored one is never uploaded:
        # the wiki refuses such an upload as an error, which would fail the run, and
        # under --force that is every unchanged page.
        file_state = bot.get_file_state([sanitize_filename(p) for p in pages])
        if not args.force:
            page_revs = bot.get_page_revisions(pages)

    success = []
    skipped = []
    unchanged = []
    failed = []

    for i, page in enumerate(pages):
        print(f"\n[{i+1}/{len(pages)}] {page}", file=sys.stderr, flush=True)
        upload_name = sanitize_filename(page)
        stored = file_state.get(upload_name, {})

        # Check if PDF is already up to date
        if not args.force and not args.no_upload:
            current_rev = page_revs.get(page)
            pdf_rev = stored.get("revid")
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
                if stored.get("sha1") == file_sha1(pdf_path):
                    print("  Identical to stored file, upload skipped", file=sys.stderr)
                    unchanged.append(page)
                    continue
                print(f"  Uploading as {upload_name}...", file=sys.stderr)
                comment = (f"Auto-generated from revision {revid}. "
                           f"https://github.com/wirenboard/wiki-pdf-typst")
                result = bot.upload_file(upload_name, pdf_path, comment=comment)
                if upload_is_no_change(result):
                    # Raced with another run, or the hash lookup found nothing.
                    print("  Wiki already holds this exact file", file=sys.stderr)
                    unchanged.append(page)
                    continue
                print(f"  Uploaded.", file=sys.stderr)

            success.append(page)
        except Exception as e:
            elapsed = time.time() - t0
            err = str(e).split("\n")[0][:100]
            print(f"  FAILED ({elapsed:.1f}s): {err}", file=sys.stderr)
            failed.append((page, err))

    print(f"\n=== Results: {len(success)} updated, {len(skipped)} up-to-date, "
          f"{len(unchanged)} regenerated but unchanged, {len(failed)} failed ===",
          file=sys.stderr)
    for page, err in failed:
        print(f"  FAIL: {page}: {err}", file=sys.stderr)

    if unchanged and not args.force:
        # Reaching this without --force means the staleness check could not settle:
        # either the stored file carries no "Auto-generated from revision N" comment,
        # or the page reports no revision id. Such a page rebuilds on every run.
        print(f"\nWARNING: {len(unchanged)} page(s) rebuilt to bytes already stored, without "
              f"--force. Their revision bookkeeping is broken, so they rebuild every run:",
              file=sys.stderr)
        for page in unchanged:
            print(f"  {page}", file=sys.stderr)

    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
