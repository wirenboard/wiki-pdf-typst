# wiki2pdf — Wiren Board Wiki to PDF Manual Generator

Converts [wiki.wirenboard.com](https://wiki.wirenboard.com) pages into professionally formatted PDF manuals using [Typst](https://typst.app/).

## How It Works

1. Wiki editors add `{{Wbincludes:pdf}}` to device pages they want as PDFs
2. A GitHub Actions workflow runs every 10 minutes, discovers those pages, and generates/uploads PDFs
3. Each wiki page shows a download link to the latest PDF via the template

## Usage

### Single page (local)

```bash
python3 wiki2pdf.py "https://wiki.wirenboard.com/wiki/ZMCT205D"
python3 wiki2pdf.py "https://wiki.wirenboard.com/wiki/PageName" -o custom_output.pdf
python3 wiki2pdf.py "https://wiki.wirenboard.com/wiki/PageName" --keep-typst
```

### Publish all pages to wiki

```bash
export WIKI_BOT_USER="EvgenyBoger@PdfUploader"
export WIKI_BOT_PASS="..."
python3 wiki_publish.py              # discover pages, generate stale PDFs, upload
python3 wiki_publish.py --dry-run    # list pages without generating
python3 wiki_publish.py --force      # regenerate all, ignoring staleness
python3 wiki_publish.py --page NAME  # process a single page
python3 wiki_publish.py --no-upload  # generate locally without uploading
```

### Add the template to wiki pages

```bash
export WIKI_BOT_USER="EvgenyBoger@PdfDev"
export WIKI_BOT_PASS="..."
python3 wiki_add_template.py "Page Name 1" "Page Name 2" ...
```

This adds `{{Wbincludes:pdf}}` to each page and approves the revision (requires `approverevisions` right).

## GitHub Actions

The workflow (`.github/workflows/update-pdfs.yml`) runs in two modes:

### Scheduled (every 10 minutes)
- Queries the wiki for all pages with `{{Wbincludes:pdf}}`
- For each page, compares the current wiki revision with the revision stored in the uploaded PDF's comment
- Skips pages that are already up to date
- Generates and uploads only stale PDFs

### On push to master
- Triggers when code changes are pushed (converter, template, fonts, etc.)
- Runs with `--force` to regenerate ALL PDFs, since the rendering may have changed
- Ignores pushes to non-code files (README, .gitignore, utility scripts)

### Secrets required
Set these in the repository settings at Settings → Secrets → Actions:
- `WIKI_BOT_USER` — MediaWiki bot username (e.g. `EvgenyBoger@PdfUploader`)
- `WIKI_BOT_PASS` — MediaWiki bot password

The bot account needs `upload`, `writeapi`, and `wb_editors` group membership on the wiki.

## Setup (local development)

Requires Python 3.11+ with dependencies:

```bash
pip install -r requirements.txt
```

The Typst binary should be at `bin/typst`:

```bash
curl -sL https://github.com/typst/typst/releases/download/v0.13.1/typst-x86_64-unknown-linux-musl.tar.xz | tar xJ
mkdir -p bin
mv typst-x86_64-unknown-linux-musl/typst bin/typst
```

Custom fonts go in `fonts/` (PT Sans is included).

## Project Structure

```
wiki2pdf.py              Single-page CLI converter
wiki_publish.py          Batch: discover pages, generate PDFs, upload to wiki
wiki_add_template.py     Add {{Wbincludes:pdf}} to pages and approve
batch_generate.py        Local batch generation (hardcoded page list)
audit_pdfs.py            Check generated PDFs for rendering issues
lib/
  fetcher.py             MediaWiki API client, image downloader, section inliner
  html_converter.py      HTML-to-Typst conversion engine
  typst_runner.py        Typst compilation wrapper (with colspan auto-fix)
  wiki_api.py            MediaWiki bot client (login, upload, page queries)
templates/
  manual.typ             Typst template (layout, styles, cover page, TOC)
fonts/                   Font files (PT Sans)
.github/workflows/
  update-pdfs.yml        GitHub Actions workflow
```

## Architecture Decisions

### Data source: MediaWiki `action=parse` API (not raw wikitext)

The wiki uses many `{{Wbincludes:...}}` transclusion templates with parameters (e.g. `note=true`, `no_description=true`). Parsing raw wikitext would require reimplementing the MediaWiki template engine. The `action=parse` API returns fully rendered HTML with all templates expanded, conditional content resolved, and `class="hidden"` applied to suppressed elements.

### HTML parsing (not wikitext parsing)

BeautifulSoup with `html.parser` is used to walk the rendered DOM. This is more reliable than wikitext parsing because:
- Templates are already evaluated with their parameters
- HTML structure is predictable (`<table class="wikitable">`, `<div class="thumb">`, `<span class="note">`, etc.)
- CSS classes like `hidden`, `noprint`, `mw-editsection` can be stripped in a single pass

### Section inlining

Many wiki pages have sections that are just a link to a sub-page (e.g. "Ревизии устройства" links to a separate revisions page). The fetcher detects these single-link sections and inlines the linked page's content:
- Headings in sub-content are demoted relative to the parent heading level
- Back-link paragraphs ("Перейти на страницу устройства") are removed
- Links to inlined pages are rewritten as local anchor references (`#fragment`)
- MediaWiki namespace prefixes (`File:`, `Special:`, `Template:`, etc.) are excluded from inlining

### Staleness check

When publishing, the script compares each page's current wiki revision ID against the revision stored in the uploaded PDF's file comment (`"Auto-generated from revision NNNNN"`). Pages are skipped if they match. Revision checks are batched (up to 50 pages per API call).

### Typst (not LaTeX, not Pandoc)

Typst was chosen for:
- Native PDF output with good typography
- Simple markup language that maps well from HTML
- Built-in support for tables with colspan/rowspan, figure numbering, page flipping
- `layout()` function for measuring and constraining image sizes
- `#page(flipped: true)` for landscape pages

### Image handling

- Images are downloaded in parallel (ThreadPoolExecutor, 8 workers)
- Full-resolution images are preferred over thumbnails (thumbnail URLs are converted by stripping `/thumb/` path segment)
- Portrait images (height > 1.2x width) are detected by reading PNG/JPEG headers and automatically grouped into 2-column grids when consecutive
- The `constrained-image` Typst function uses `layout()` + `measure()` to cap tall images at 50% of page height while preserving aspect ratio
- Gallery images use a stricter height limit (40%) so two fit per page
- The first content image is extracted for the cover page

### Animated GIFs

Animated GIFs are extracted into up to 8 visually diverse frames using greedy farthest-point sampling. Short animations (< 4 frames) show 2 full cycles. Each frame is captioned with its timestamp. Frames are rendered in a 4-column grid within a figure, or inline in table cells at matching size with static images.

### Table layout

Column count is determined from the header row (or mode of all rows) to avoid inflation from legend rows with oversized colspans. Layout mode depends on content width:
- **Normal**: tables with < 5 columns
- **Compact**: 5-7 columns, reduced font size (8.5pt)
- **Landscape**: 8+ columns with wide content (max row text > 80 chars) or 12+ columns; uses `#page(flipped: true)` with 7pt font

When a heading immediately precedes a landscape table, it is pulled inside the flipped page block.

Tables with `<caption>` are wrapped in `#figure(kind: table)` for auto-numbered captions. Cell background colors are resolved from both inline styles and CSS classes (`cell-green`, `cell-red`, `cell-yellow`).

The Typst compiler auto-fixes colspan overflow errors by halving the offending value and retrying (up to 20 times).

### Gallery handling

MediaWiki `<ul class="gallery">` elements are converted to individual figures with a gallery-level caption prepended (e.g. "Обновление прошивки. Выбор файла"). Gallery images use a height constraint (40% of page) instead of a width constraint for compact layout.

### Note/warning blocks

Two detection patterns:
- `<span class="note note-note">` / `<span class="note note-warning">` — semantic class-based
- `<div style="border:...;background:...">` — CSS heuristic for template-generated callout boxes

Both render as styled callout blocks with colored left border.

### Text and cell color support

Colors are resolved from multiple sources:
- CSS classes: `text-green`, `text-red`, `text-orange` for text; `cell-green`, `cell-red`, `cell-yellow` for cell backgrounds
- Inline styles: `style="color: #xxx"` and `style="background-color: #xxx"`

### Hidden content

Elements with `class="hidden"` or `class="noprint"` are stripped. This respects MediaWiki template parameters like `no_description=true` and the `{{Wbincludes:pdf}}` download block itself.

### Cover page and metadata

- First content image is extracted and placed on the cover page
- Wiki page URL is shown and clickable
- Revision ID and timestamp from the wiki API
- Page header on every page links back to the wiki article

### Font

PT Sans (Paratype) — free sans-serif with full Cyrillic support. Custom fonts can be added to `fonts/` and referenced in `templates/manual.typ`.
