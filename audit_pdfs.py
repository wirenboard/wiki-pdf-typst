#!/usr/bin/env python3
"""Audit generated PDFs for visual issues."""

import fitz
import os
import re

output_dir = "output"
issues_found = []

for fname in sorted(os.listdir(output_dir)):
    if not fname.endswith(".pdf") or fname.startswith("ZMCT205D-"):
        continue
    if os.path.isdir(os.path.join(output_dir, fname)):
        continue
    path = os.path.join(output_dir, fname)
    name = fname.replace(".pdf", "")
    doc = fitz.open(path)
    page_count = len(doc)
    file_issues = []

    for page_num in range(page_count):
        page = doc[page_num]
        text = page.get_text()
        pw, ph = page.rect.width, page.rect.height
        is_landscape = pw > ph

        # 1. Empty pages (skip cover and TOC)
        content_text = re.sub(r"\d+ / \d+", "", text).strip()
        if len(content_text) < 30 and page_num > 2:
            file_issues.append(f"  p{page_num+1}: nearly empty page")

        # 2. Images taller than 55% of page (portrait pages only)
        for img_info in page.get_images(full=True):
            xref = img_info[0]
            for r in page.get_image_rects(xref):
                if not is_landscape and r.height > ph * 0.55:
                    file_issues.append(f"  p{page_num+1}: tall image ({r.height/ph*100:.0f}% of page)")

        # 3. Raw Typst markup leaking through
        for marker in ["#table(", "#figure(", "#image(", "#strong[", "#emph[", "constrained-image"]:
            if marker in text:
                file_issues.append(f"  p{page_num+1}: raw markup '{marker}' in text")

        # 4. Visible escape sequences
        for esc in ["\\#", "\\@", "\\$", "\\~"]:
            if esc in text:
                file_issues.append(f"  p{page_num+1}: escaped char '{esc}' visible")

    doc.close()

    if file_issues:
        unique = list(dict.fromkeys(file_issues))
        issues_found.append((name, unique))
        print(f"{'ISSUES':>7} {name} ({page_count} pages, {len(unique)} issues)")
        for issue in unique[:8]:
            print(issue)
        if len(unique) > 8:
            print(f"  ... and {len(unique) - 8} more")
    else:
        print(f"{'OK':>7} {name} ({page_count} pages)")

total = len([f for f in os.listdir(output_dir) if f.endswith(".pdf") and not f.startswith("ZMCT205D-") and not os.path.isdir(os.path.join(output_dir, f))])
print(f"\n=== Summary: {len(issues_found)} files with issues out of {total} PDFs ===")
if issues_found:
    print("\nFiles with issues:")
    for name, iss in issues_found:
        print(f"  {name}: {len(iss)} issues")
