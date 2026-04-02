# wiki2pdf — Wiren Board Wiki to PDF Manual Generator

Converts [wiki.wirenboard.com](https://wiki.wirenboard.com) pages into professionally formatted PDF manuals using [Typst](https://typst.app/).

## Usage

```bash
python3 wiki2pdf.py "https://wiki.wirenboard.com/wiki/ZMCT205D"
python3 wiki2pdf.py "https://wiki.wirenboard.com/wiki/WB-MGE_v.3_Modbus_Ethernet_Gateway"
python3 wiki2pdf.py "https://wiki.wirenboard.com/wiki/PageName" -o custom_output.pdf
python3 wiki2pdf.py "https://wiki.wirenboard.com/wiki/PageName" --keep-typst
```

Output PDFs are saved to `output/`.

## Setup

Requires Python 3.11+ with `beautifulsoup4` and `requests`.

```bash
pip install beautifulsoup4 requests
```

The Typst binary should be at `bin/typst`. Download from [typst releases](https://github.com/typst/typst/releases):

```bash
curl -sL https://github.com/typst/typst/releases/download/v0.13.1/typst-x86_64-unknown-linux-musl.tar.xz | tar xJ
mv typst-x86_64-unknown-linux-musl/typst bin/typst
```

Custom fonts go in `fonts/` (PT Sans is included).

## Project Structure

```
wiki2pdf.py              CLI entry point
lib/
  fetcher.py             MediaWiki API client, image downloader, section inliner
  html_converter.py      HTML-to-Typst conversion engine
  typst_runner.py        Typst compilation wrapper
templates/
  manual.typ             Typst template (layout, styles, cover page, TOC)
fonts/                   Font files (PT Sans, etc.)
bin/typst                Typst binary
output/                  Generated PDFs and cached images
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
- The first content image is extracted for the cover page

### Table layout

Tables are rendered with `columns: (auto,) * N` for content-aware column sizing. The layout mode depends on content width:
- **Normal**: tables with < 5 columns
- **Compact**: 5-7 columns, reduced font size (8.5pt)
- **Landscape**: 8+ columns with wide content (max row text > 80 chars) or 12+ columns regardless; uses `#page(flipped: true)` with 7pt font and 4pt cell padding

When a heading immediately precedes a landscape table, it is pulled inside the `#page(flipped: true)` block to keep them on the same page.

Tables with `<caption>` elements are wrapped in `#figure(kind: table)` for auto-numbered captions ("Таблица 1: ..."). Landscape tables use a plain italic caption instead since `#page` cannot be nested inside `#figure`.

### Gallery handling

MediaWiki `<ul class="gallery">` elements are converted to individual figures. The gallery-level caption is prepended to each figure's individual caption (e.g. "Обновление прошивки. Выбор файла").

### Note/warning blocks

Two detection patterns:
- `<span class="note note-note">` / `<span class="note note-warning">` — semantic class-based
- `<div style="border:...;background:...">` — CSS heuristic for template-generated callout boxes

Both render as styled callout blocks with colored left border.

### Text color support

Colors are resolved from two sources:
- CSS classes: `text-green`, `text-red`, `text-orange`, etc. (mapped to hex values)
- Inline styles: `style="color: #xxx"` (parsed with regex, excluding `background-color`)

### Hidden content

Elements with `class="hidden"` are stripped. This respects MediaWiki template parameters like `no_description=true` which add `class="hidden"` to conditionally suppressed content.

### Cover page and metadata

- First content image is extracted and placed on the cover page
- Wiki page URL is shown and clickable
- Revision ID and timestamp are fetched via a second API call (`action=query`)
- Page header on every page links back to the wiki article

### SSL verification

Disabled by default (`VERIFY_SSL = False`) for environments with missing CA certificates. Controlled by a module-level constant in `fetcher.py`.

### Font

PT Sans (Paratype) — free sans-serif with full Cyrillic support. Custom fonts can be added to `fonts/` and referenced in `templates/manual.typ`.
