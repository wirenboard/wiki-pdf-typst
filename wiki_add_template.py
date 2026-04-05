#!/usr/bin/env python3
"""Add {{Wbincludes:pdf}} to wiki pages and approve the revision."""

import argparse
import os
import sys

from lib.wiki_api import WikiBot

BOT_USER = os.environ.get("WIKI_BOT_USER", "")
BOT_PASS = os.environ.get("WIKI_BOT_PASS", "")

TEMPLATE_TAG = "{{Wbincludes:pdf}}"


def main():
    parser = argparse.ArgumentParser(
        description="Add {{Wbincludes:pdf}} template to wiki pages and approve"
    )
    parser.add_argument("pages", nargs="+", help="Page names to process")
    args = parser.parse_args()

    if not BOT_USER or not BOT_PASS:
        print("Error: set WIKI_BOT_USER and WIKI_BOT_PASS environment variables",
              file=sys.stderr)
        sys.exit(1)

    bot = WikiBot()
    bot.login(BOT_USER, BOT_PASS)
    print("Logged in.", file=sys.stderr)

    for page in args.pages:
        print(f"\n{page}:", file=sys.stderr)

        # Get current content
        resp = bot.session.get(bot.api_url, params={
            "action": "query", "titles": page,
            "prop": "revisions", "rvprop": "content|ids",
            "rvslots": "main", "format": "json",
        }, timeout=30)
        pg = next(iter(resp.json()["query"]["pages"].values()))

        if "missing" in pg:
            print(f"  Page not found", file=sys.stderr)
            continue

        content = pg["revisions"][0]["slots"]["main"]["*"]

        if TEMPLATE_TAG in content:
            print(f"  Template already present", file=sys.stderr)
        else:
            content = TEMPLATE_TAG + "\n" + content
            bot.edit_page(page, content, summary="Add PDF download template")
            print(f"  Added template", file=sys.stderr)

        # Approve latest revision
        resp = bot.session.get(bot.api_url, params={
            "action": "query", "titles": page,
            "prop": "revisions", "rvprop": "ids",
            "format": "json",
        }, timeout=15)
        pg = next(iter(resp.json()["query"]["pages"].values()))
        revid = pg["revisions"][0]["revid"]

        token = bot.get_csrf_token()
        resp = bot.session.post(bot.api_url, data={
            "action": "approve", "revid": str(revid),
            "token": token, "format": "json",
        }, timeout=15)
        result = resp.json()
        if "approve" in result:
            print(f"  Approved (rev {revid})", file=sys.stderr)
        else:
            err = result.get("error", {}).get("info", "unknown error")
            print(f"  Approve failed: {err}", file=sys.stderr)


if __name__ == "__main__":
    main()
