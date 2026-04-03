#!/usr/bin/env python3
"""Convert Wiren Board wiki pages to PDF manuals using Typst."""

import argparse
import os
import sys

from lib import fetcher, html_converter, typst_runner


BASE_URL = "https://wiki.wirenboard.com"


def generate_pdf(url: str, output_pdf: str = None, keep_typst: bool = False) -> str:
    """Generate a PDF from a wiki URL. Returns path to the generated PDF."""
    base_url, page_name = fetcher.extract_page_name(url)
    print(f"Page: {page_name}", file=sys.stderr)

    safe_name = page_name.replace("/", "_").replace(" ", "_")
    output_dir = os.path.join(os.path.dirname(__file__) or ".", "output")
    os.makedirs(output_dir, exist_ok=True)
    output_pdf = output_pdf or os.path.join(output_dir, f"{safe_name}.pdf")
    typ_file = os.path.join(output_dir, f"{safe_name}.typ")

    # Fetch page
    print("Fetching page...", file=sys.stderr)
    page_data = fetcher.fetch_page(base_url, page_name)
    html = page_data["html"]
    title = page_data["title"]
    revid = page_data["revid"]
    revtimestamp = page_data["revtimestamp"]
    print(f"Title: {title}", file=sys.stderr)

    # Inline link-only sections
    print("Inlining referenced sections...", file=sys.stderr)
    html = fetcher.inline_link_sections(html, base_url)

    # Download images
    print("Downloading images...", file=sys.stderr)
    image_map, gif_frames = fetcher.download_images(html, base_url, output_dir)
    print(f"Downloaded {len(image_map)} images", file=sys.stderr)

    # Convert HTML to Typst
    print("Converting to Typst...", file=sys.stderr)
    typst_content, cover_image = html_converter.convert(html, image_map, base_url, gif_frames)

    # Build the full .typ document
    template_path = os.path.join(os.path.dirname(__file__) or ".", "templates", "manual.typ")
    with open(template_path, "r") as f:
        template = f.read()

    escaped_title = title.replace("\\", "\\\\").replace('"', '\\"')
    wiki_url = f"{base_url}/wiki/{page_name}"
    rev_date = ""
    if revtimestamp:
        rev_date = revtimestamp[:10].split("-")
        rev_date = f"{rev_date[2]}.{rev_date[1]}.{rev_date[0]}"

    full_doc = template.replace(
        '#let doc-title = ""', f'#let doc-title = "{escaped_title}"'
    ).replace(
        '#let doc-date = ""', f'#let doc-date = "{rev_date}"'
    ).replace(
        '#let doc-cover-image = ""',
        f'#let doc-cover-image = "{cover_image}"' if cover_image else '#let doc-cover-image = ""'
    ).replace(
        '#let doc-url = ""', f'#let doc-url = "{wiki_url}"'
    ).replace(
        '#let doc-revid = ""', f'#let doc-revid = "{revid}"'
    )

    with open(typ_file, "w") as f:
        f.write(full_doc)
        f.write("\n// === Generated content ===\n\n")
        f.write(typst_content)

    # Compile
    print("Compiling PDF...", file=sys.stderr)
    typst_runner.compile(typ_file, output_pdf)
    print(f"PDF saved: {output_pdf}", file=sys.stderr)

    if not keep_typst:
        os.remove(typ_file)
    else:
        print(f"Typst source: {typ_file}", file=sys.stderr)

    return output_pdf


def main():
    parser = argparse.ArgumentParser(
        description="Convert wiki.wirenboard.com pages to PDF manuals"
    )
    parser.add_argument("url", help="Wiki page URL")
    parser.add_argument("-o", "--output", help="Output PDF path")
    parser.add_argument("--keep-typst", action="store_true",
                        help="Keep intermediate .typ file")
    args = parser.parse_args()

    try:
        generate_pdf(args.url, args.output, args.keep_typst)
    except RuntimeError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
