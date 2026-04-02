"""HTML to Typst conversion engine."""

import os
import re
import struct
from bs4 import BeautifulSoup, Comment, NavigableString, Tag


# Single-pass escape table for Typst special characters
_ESCAPE_TABLE = str.maketrans({
    "\\": "\\\\",
    "#": "\\#",
    "*": "\\*",
    "_": "\\_",
    "`": "\\`",
    "@": "\\@",
    "$": "\\$",
    "~": "\\~",
    "<": "\\<",
    ">": "\\>",
})

# Pre-compiled regexes for style extraction
_RE_BG_HEX = re.compile(r"background(?:-color)?\s*:\s*(#[0-9a-fA-F]{3,8})")
_RE_BG_NAMED = re.compile(r"background(?:-color)?\s*:\s*(\w+)")
_RE_TEXT_COLOR = re.compile(r"(?:^|;)\s*color\s*:\s*(#[0-9a-fA-F]{3,8})")

_NAMED_COLORS = {
    "green": "#00aa00", "red": "#ff0000", "yellow": "#ffff00",
    "lightgreen": "#90ee90", "lightyellow": "#ffffe0",
    "lightcoral": "#f08080", "white": "#ffffff",
}

# CSS class → color mapping for MediaWiki text-color classes
_TEXT_COLOR_CLASSES = {
    "text-green": "#00aa00",
    "text-red": "#ff0000",
    "text-blue": "#0000ff",
    "text-orange": "#ff8c00",
    "text-yellow": "#cccc00",
    "text-gray": "#808080",
    "text-grey": "#808080",
    "text-white": "#ffffff",
    "text-purple": "#800080",
    "text-brown": "#8b4513",
}

# Elements to strip from the DOM before conversion
_STRIP_IDS = {"toc", "catlinks"}
_STRIP_CLASSES = {"mw-editsection", "noprint", "navbox", "hidden"}
_STRIP_TAGS = {"script", "style"}

# Regex for extracting image paths from generated figure lines
_RE_FIGURE_IMG = re.compile(r'constrained-image\("([^"]+)"')

# Structural MediaWiki div IDs that should not get Typst labels
_SKIP_DIV_IDS = {"mw-parser-output", "mw-content-text", "content", "bodyContent", "mw-body"}


def convert(html: str, image_map: dict[str, str], base_url: str,
            gif_frames: dict[str, list[str]] | None = None) -> tuple[str, str | None]:
    """Convert MediaWiki HTML to Typst markup string.

    Returns (typst_content, first_image_path_or_None).
    """
    converter = HtmlToTypstConverter(image_map, base_url, gif_frames or {})
    content = converter.convert(html)
    return content, converter.cover_image


class HtmlToTypstConverter:
    def __init__(self, image_map: dict[str, str], base_url: str,
                 gif_frames: dict[str, list[str]] | None = None):
        self.image_map = image_map
        self.base_url = base_url
        self.gif_frames = gif_frames or {}
        self.parts: list[str] = []
        self.list_depth = 0
        self.in_table = False
        self.in_code = False
        self.cover_image: str | None = None

    def convert(self, html: str) -> str:
        soup = BeautifulSoup(html, "html.parser")
        self._strip_unwanted(soup)
        content = soup.find("div", class_="mw-parser-output")
        if not content:
            content = soup
        self._extract_cover_image(content)
        self._process_children(content)
        self._merge_narrow_figures()
        return "\n".join(self.parts)

    def _merge_narrow_figures(self):
        """Post-process: group consecutive narrow (portrait) figures into grids."""
        # Parse parts into blocks separated by blank lines
        # A figure block is: "", "#figure(", "  constrained-image(...),", ["  caption: ...,"], ")", ""

        i = 0
        new_parts = []
        while i < len(self.parts):
            # Detect start of a figure block
            if self.parts[i].startswith("#figure("):
                # Collect consecutive figure blocks
                run = []
                while i < len(self.parts) and self.parts[i].startswith("#figure("):
                    # Gather lines of this figure
                    fig_lines = []
                    fig_lines.append(self.parts[i])  # "#figure("
                    i += 1
                    while i < len(self.parts) and self.parts[i] != ")":
                        fig_lines.append(self.parts[i])
                        i += 1
                    if i < len(self.parts):
                        fig_lines.append(self.parts[i])  # ")"
                        i += 1
                    # Skip trailing blank line
                    if i < len(self.parts) and self.parts[i] == "":
                        i += 1
                    run.append(fig_lines)

                if len(run) < 2:
                    # Single figure, emit as-is
                    new_parts.append("")
                    new_parts.extend(run[0])
                    new_parts.append("")
                else:
                    # Check which figures are narrow (portrait)
                    narrow = []
                    for fig_lines in run:
                        img_path = None
                        for line in fig_lines:
                            m = _RE_FIGURE_IMG.search(line)
                            if m:
                                img_path = m.group(1)
                                break
                        is_portrait = False
                        if img_path:
                            is_portrait = self._is_portrait(img_path)
                        narrow.append(is_portrait)

                    # Group consecutive portrait figures into grids
                    j = 0
                    while j < len(run):
                        if narrow[j] and j + 1 < len(run) and narrow[j + 1]:
                            # 2+ consecutive portrait figures — group into grid
                            grid_figs = []
                            while j < len(run) and narrow[j]:
                                grid_figs.append(run[j])
                                j += 1
                            cols = min(len(grid_figs), 2)
                            new_parts.append("")
                            new_parts.append(f"#grid(")
                            new_parts.append(f"  columns: {cols},")
                            new_parts.append(f"  gutter: 12pt,")
                            for fig in grid_figs:
                                # Strip leading # from lines for code context
                                fixed = []
                                for line in fig:
                                    if line.startswith("#"):
                                        fixed.append(line[1:])
                                    else:
                                        fixed.append(line)
                                new_parts.append("  " + "\n  ".join(fixed) + ",")
                            new_parts.append(")")
                            new_parts.append("")
                        else:
                            new_parts.append("")
                            new_parts.extend(run[j])
                            new_parts.append("")
                            j += 1

                continue
            new_parts.append(self.parts[i])
            i += 1

        self.parts = new_parts

    def _is_portrait(self, relative_path: str) -> bool:
        """Check if an image is portrait (height > 1.2 * width) by reading PNG/JPEG header."""
        # Find the actual file in output dir
        for base in ("output", "."):
            path = os.path.join(base, relative_path)
            if os.path.exists(path):
                break
        else:
            return False
        try:
            with open(path, "rb") as f:
                data = f.read(64 * 1024)
            if data[:8] == b'\x89PNG\r\n\x1a\n':
                w = struct.unpack(">I", data[16:20])[0]
                h = struct.unpack(">I", data[20:24])[0]
            elif data[:2] == b'\xff\xd8':  # JPEG — scan for SOF0/SOF2 marker
                idx = data.find(b'\xff\xc0')
                if idx == -1:
                    idx = data.find(b'\xff\xc2')
                if idx == -1:
                    return False
                h = struct.unpack(">H", data[idx+5:idx+7])[0]
                w = struct.unpack(">H", data[idx+7:idx+9])[0]
            else:
                return False
            return h > w * 1.2
        except (OSError, struct.error):
            return False

    def _extract_cover_image(self, content):
        """Find the first content image and remove it from the tree (for the cover page)."""
        # Look for the first thumb/figure div or standalone img
        thumb = content.find("div", class_="thumb")
        if thumb:
            img = thumb.find("img")
            if img:
                src = img.get("src", "")
                if src and src in self.image_map:
                    self.cover_image = self.image_map[src]
                    thumb.decompose()
                    return
        # Fallback: first <img> in content
        for img in content.find_all("img"):
            src = img.get("src", "")
            if src and src in self.image_map:
                self.cover_image = self.image_map[src]
                img.decompose()
                return

    def _strip_unwanted(self, soup: BeautifulSoup):
        """Remove elements that shouldn't appear in the PDF (single traversal)."""
        to_remove = []
        for el in soup.find_all(True):
            if el.name in _STRIP_TAGS:
                to_remove.append(el)
            elif el.get("id") in _STRIP_IDS:
                to_remove.append(el)
            else:
                classes = el.get("class") or []
                if any(c in _STRIP_CLASSES for c in classes):
                    to_remove.append(el)
        for el in to_remove:
            el.decompose()

    def _emit(self, text: str):
        self.parts.append(text)

    def _emit_blank(self):
        """Emit a blank line if the last line wasn't already blank."""
        if self.parts and self.parts[-1] != "":
            self.parts.append("")

    def _process_children(self, node: Tag):
        for child in node.children:
            self._process_node(child)

    def _process_node(self, node):
        if isinstance(node, Comment):
            return
        if isinstance(node, NavigableString):
            text = str(node)
            if self.in_code:
                if text.strip():
                    self.parts.append(text)
                return
            if not text.strip():
                return
            self._emit(self._escape(text))
            return

        if not isinstance(node, Tag):
            return

        tag = node.name

        # Block-level elements with special handling
        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self._process_heading(node)
        elif tag == "p":
            self._process_paragraph(node)
        elif tag == "pre":
            self._process_code_block(node)
        elif tag == "ul" and "gallery" in (node.get("class") or []):
            self._process_gallery(node)
        elif tag == "ul":
            self._process_list(node, ordered=False)
        elif tag == "ol":
            self._process_list(node, ordered=True)
        elif tag == "li":
            # Orphan <li> outside a list — process children
            self._process_children(node)
        elif tag == "dl":
            self._process_dl(node)
        elif tag == "table":
            self._process_table(node)
        elif tag == "img":
            self._process_image(node)
        elif tag == "div":
            self._process_div(node)
        elif tag == "hr":
            self._emit_blank()
            self._emit("#line(length: 100%)")
            self._emit_blank()
        elif tag == "blockquote":
            self._emit_blank()
            self._emit(f"#quote(block: true)[{self._inline_content(node)}]")
            self._emit_blank()
        elif tag == "dd":
            self._emit_blank()
            self._emit(f"#pad(left: 1.5em)[{self._inline_content(node)}]")
            self._emit_blank()
        else:
            # Inline elements (b, i, code, a, span, sup, sub, br) and unknown tags
            result = self._inline_from_tag(node)
            if result:
                self._emit(result)

    def _process_heading(self, node: Tag):
        level_map = {"h1": "=", "h2": "=", "h3": "==", "h4": "===", "h5": "====", "h6": "====="}
        prefix = level_map.get(node.name, "=")
        text = self._get_text(node).strip()
        if not text:
            return
        self._emit_blank()
        self._emit(f"{prefix} {text}")
        self._emit_blank()

    def _process_paragraph(self, node: Tag):
        content = self._inline_content(node).strip()
        if not content:
            return
        self._emit_blank()
        self._emit(content)
        self._emit_blank()

    def _process_code_block(self, node: Tag):
        self._emit_blank()
        code_text = node.get_text()
        lang = ""
        highlight_div = node.find_parent("div", class_=re.compile(r"mw-highlight"))
        if highlight_div:
            for cls in (highlight_div.get("class") or []):
                m = re.match(r"mw-highlight-lang-(\w+)", cls)
                if m:
                    lang = m.group(1)
                    break
        self._emit(f"```{lang}")
        self._emit(code_text.rstrip())
        self._emit("```")
        self._emit_blank()

    def _process_list(self, node: Tag, ordered: bool):
        was_in_list = self.list_depth > 0
        if not was_in_list:
            self._emit_blank()
        self.list_depth += 1
        marker = "+" if ordered else "-"

        for child in node.children:
            if isinstance(child, Tag) and child.name == "li":
                indent = "  " * (self.list_depth - 1)
                nested_lists = child.find_all(["ul", "ol"], recursive=False)
                if nested_lists:
                    pre_text_parts = []
                    for c in child.children:
                        if isinstance(c, Tag) and c.name in ("ul", "ol"):
                            break
                        if isinstance(c, NavigableString):
                            t = str(c).strip()
                            if t:
                                pre_text_parts.append(self._escape(t))
                        elif isinstance(c, Tag):
                            pre_text_parts.append(self._inline_from_tag(c))
                    pre_text = " ".join(pre_text_parts).strip()
                    if pre_text:
                        self._emit(f"{indent}{marker} {pre_text}")
                    for nl in nested_lists:
                        self._process_list(nl, ordered=(nl.name == "ol"))
                else:
                    content = self._inline_content(child).strip()
                    if content:
                        self._emit(f"{indent}{marker} {content}")

        self.list_depth -= 1
        if not was_in_list:
            self._emit_blank()

    def _process_dl(self, node: Tag):
        """Handle definition lists (used for indentation in wiki)."""
        for child in node.children:
            if isinstance(child, Tag):
                if child.name == "dt":
                    text = self._inline_content(child).strip()
                    if text:
                        self._emit_blank()
                        self._emit(f"#strong[{text}]")
                elif child.name == "dd":
                    text = self._inline_content(child).strip()
                    if text:
                        self._emit(f"#pad(left: 1.5em)[{text}]")
                else:
                    self._process_node(child)

    def _process_table(self, node: Tag):
        self._emit_blank()
        old_in_table = self.in_table
        self.in_table = True

        # Extract caption for figure-style labeling
        caption_text = ""
        caption_el = node.find("caption")
        if caption_el:
            caption_text = self._inline_content(caption_el).strip()

        rows = []
        for tr in node.find_all("tr", recursive=False):
            rows.append(tr)
        if not rows:
            for section in node.find_all(["thead", "tbody"], recursive=False):
                for tr in section.find_all("tr", recursive=False):
                    rows.append(tr)

        if not rows:
            self.in_table = old_in_table
            return

        num_cols = 0
        max_row_text = 0
        for row in rows:
            cols_in_row = 0
            row_text = 0
            for cell in row.find_all(["th", "td"], recursive=False):
                cols_in_row += int(cell.get("colspan", 1))
                row_text += len(cell.get_text().strip())
            num_cols = max(num_cols, cols_in_row)
            max_row_text = max(max_row_text, row_text)

        if num_cols == 0:
            self.in_table = old_in_table
            return

        # ~80 chars fit on portrait A4 at 10pt; landscape gives ~120 chars.
        # With compact 8.5pt font, portrait fits ~95 chars.
        use_figure_caption = False
        needs_landscape = num_cols >= 8 and (max_row_text > 80 or num_cols >= 12)
        if needs_landscape:
            table_mode = "landscape"
            # Pull preceding heading into the flipped page so they stay together
            heading_line = None
            if len(self.parts) >= 2 and self.parts[-1] == "":
                candidate = self.parts[-2]
                if re.match(r"=+ ", candidate):
                    heading_line = self.parts.pop(-2)
                    # Also remove the blank line before the heading if present
                    if self.parts and self.parts[-1] == "":
                        self.parts.pop()
            self._emit("#page(flipped: true)[")
            if heading_line:
                self._emit(heading_line)
            if caption_text:
                self._emit(f"#align(center, text(size: 9pt, style: \"italic\")[{caption_text}])")
            self._emit("#set text(size: 7pt)")
        elif num_cols >= 5:
            table_mode = "compact"
            self._emit("#block(width: 100%)[")
            self._emit("#set text(size: 8.5pt)")
        else:
            table_mode = "normal"

        # Wrap in figure for auto-numbered caption (only for non-landscape tables)
        if caption_text and table_mode != "landscape":
            self._emit(f"#figure(kind: table, caption: [{caption_text}])[")
            use_figure_caption = True

        self._emit("#table(")
        self._emit(f"  columns: (auto,) * {num_cols},")
        if table_mode == "landscape":
            self._emit("  inset: 4pt,")
        self._emit("  align: left,")

        # Determine header row count
        header_rows = 0
        first_row = rows[0]
        first_cells = first_row.find_all(["th", "td"], recursive=False)
        if first_cells and all(c.name == "th" for c in first_cells):
            max_rowspan = max(int(c.get("rowspan", 1)) for c in first_cells)
            header_rows = max(1, max_rowspan)
            for i in range(1, len(rows)):
                cells_i = rows[i].find_all(["th", "td"], recursive=False)
                if cells_i and all(c.name == "th" for c in cells_i):
                    header_rows = max(header_rows, i + 1)
                elif i >= max_rowspan:
                    break

        if header_rows > 0:
            self._emit("  table.header(")

        for row_idx, tr in enumerate(rows):
            cells = tr.find_all(["th", "td"], recursive=False)

            # Sum of all explicit colspans in this row
            row_explicit = sum(int(c.get("colspan", 1)) for c in cells)

            for cell in cells:
                content = self._inline_content(cell).strip()
                colspan = int(cell.get("colspan", 1))
                rowspan = int(cell.get("rowspan", 1))
                fill_color = self._extract_bg_color(cell)

                # Fix colspan overflow from rowspan-occupied columns
                if len(cells) == 1 and colspan >= num_cols:
                    # Single-cell row spanning all: drop colspan
                    colspan = 1
                elif row_explicit > num_cols and colspan > 1:
                    # Row total exceeds table — scale down proportionally
                    colspan = max(1, colspan * num_cols // row_explicit)
                elif len(cells) > 1 and colspan > num_cols // 2:
                    # Multi-cell row with large colspan — likely rowspan conflict.
                    # Cap so total explicit colspans fit in num_cols.
                    other_cols = sum(int(c.get("colspan", 1)) for c in cells if c is not cell)
                    colspan = min(colspan, max(1, num_cols - other_cols))
                colspan = min(colspan, num_cols)

                cell_args = []
                if colspan > 1:
                    cell_args.append(f"colspan: {colspan}")
                if rowspan > 1:
                    cell_args.append(f"rowspan: {rowspan}")
                if fill_color:
                    cell_args.append(f"fill: rgb(\"{fill_color}\")")
                if row_idx < header_rows and cell.name == "th":
                    content = f"#strong[{content}]" if content else ""

                if cell_args:
                    args = ", ".join(cell_args)
                    self._emit(f"    table.cell({args})[{content}],")
                else:
                    self._emit(f"    [{content}],")

            if row_idx == header_rows - 1 and header_rows > 0:
                self._emit("  ),")

        self._emit(")")  # close #table(
        if table_mode != "normal":
            self._emit("]")
        if use_figure_caption:
            self._emit("]")  # close #figure(...)[
        self._emit_blank()
        self.in_table = old_in_table

    def _process_image(self, node: Tag):
        src = node.get("src", "")
        if not src:
            return
        width = node.get("width")
        if width and str(width).isdigit() and int(width) < 20:
            return

        local_path = self.image_map.get(src)
        if not local_path:
            return

        if self.in_table:
            self._emit(f'#image("{local_path}", width: 80%)')
        else:
            thumb = node.find_parent("div", class_="thumb")
            if thumb:
                return  # Will be handled by _process_div
            self._emit(f'#constrained-image("{local_path}", width: 80%)')

    def _process_div(self, node: Tag):
        el_id = node.get("id")
        if el_id and isinstance(el_id, str) and el_id not in _SKIP_DIV_IDS:
            # Sanitize: Typst labels only allow alphanumeric, hyphens, underscores
            safe_id = re.sub(r"[^\w-]", "", el_id)
            if safe_id:
                self._emit(f"#metadata(none) <{safe_id}>")

        classes = node.get("class") or []

        if "thumb" in classes:
            self._process_figure(node)
            return

        if any("mw-highlight" in c for c in classes):
            pre = node.find("pre")
            if pre:
                self._process_code_block(pre)
                return

        # Warning/note boxes
        style = node.get("style") or ""
        if "border" in style and ("background" in style or "padding" in style):
            content = self._inline_content(node).strip()
            if content:
                self._emit_blank()
                self._emit(f"#note-box[{content}]")
                self._emit_blank()
            return

        self._process_children(node)

    def _process_gallery(self, node: Tag):
        """Handle <ul class="gallery"> image galleries — render each as a normal figure."""
        gallery_caption = ""
        caption_li = node.find("li", class_="gallerycaption")
        if caption_li:
            gallery_caption = self._get_text(caption_li).strip()

        for item in node.find_all("li", class_="gallerybox"):
            img = item.find("img")
            if not img:
                continue
            src = img.get("src", "")
            local_path = self.image_map.get(src)
            if not local_path:
                continue
            caption_div = item.find("div", class_="gallerytext")
            caption = ""
            if caption_div:
                caption = self._inline_content(caption_div).strip()
            if gallery_caption and caption:
                caption = f"{self._escape(gallery_caption)}. {caption}"
            elif gallery_caption:
                caption = self._escape(gallery_caption)
            self._emit_figure(local_path, caption, src)

    def _emit_figure(self, local_path: str, caption: str = "", src: str = ""):
        """Emit a Typst figure with a constrained image and optional caption.
        For animated GIFs, renders a grid of extracted frames instead."""
        gif_data = self.gif_frames.get(src) if src else None
        self._emit_blank()
        if gif_data:
            frame_paths, timestamps = gif_data
            cols = min(4, len(frame_paths))
            self._emit('#figure(')
            self._emit(f'  grid(columns: {cols}, gutter: 6pt,')
            for frame_path, ts_ms in zip(frame_paths, timestamps):
                ts_str = f"{ts_ms / 1000:.1f} с" if ts_ms >= 1000 else f"{ts_ms} мс"
                self._emit(f'    figure(image("{frame_path}"), caption: [{ts_str}], numbering: none),')
            self._emit('  ),')
            if caption:
                self._emit(f'  caption: [{caption}],')
            self._emit(')')
        else:
            self._emit('#figure(')
            self._emit(f'  constrained-image("{local_path}", width: 70%),')
            if caption:
                self._emit(f'  caption: [{caption}],')
            self._emit(')')
        self._emit_blank()

    def _process_figure(self, node: Tag):
        """Handle thumbnail/figure divs."""
        img = node.find("img")
        if not img:
            self._process_children(node)
            return

        src = img.get("src", "")
        local_path = self.image_map.get(src)
        if not local_path:
            self._process_children(node)
            return

        caption_div = node.find("div", class_="thumbcaption")
        caption = ""
        if caption_div:
            magnify = caption_div.find("div", class_="magnify")
            if magnify:
                magnify.decompose()
            caption = self._inline_content(caption_div).strip()

        self._emit_figure(local_path, caption, src)

    # --- Inline rendering (single source of truth for all inline elements) ---

    def _inline_content(self, node: Tag) -> str:
        """Get inline Typst content from a node."""
        return "".join(self._inline_from_node(child) for child in node.children)

    def _inline_from_node(self, node) -> str:
        if isinstance(node, Comment):
            return ""
        if isinstance(node, NavigableString):
            text = str(node)
            if self.in_code:
                return text
            return self._escape(text)
        if not isinstance(node, Tag):
            return ""
        return self._inline_from_tag(node)

    def _inline_from_tag(self, tag: Tag) -> str:
        name = tag.name

        if name in ("b", "strong"):
            content = self._inline_content(tag).strip()
            return f"#strong[{content}]" if content else ""
        elif name in ("i", "em"):
            content = self._inline_content(tag).strip()
            return f"#emph[{content}]" if content else ""
        elif name == "code" and not self.in_code:
            text = tag.get_text()
            return f"`{text}`" if text else ""
        elif name == "a":
            href = tag.get("href", "")
            if tag.find("img"):
                return self._inline_content(tag)
            text = self._get_text(tag).strip()
            if not text:
                return ""
            if href.startswith("#"):
                return self._escape(text)
            if href.startswith("/"):
                href = self.base_url + href
            return f'#link("{href}")[{self._escape(text)}]'
        elif name == "img":
            src = tag.get("src", "")
            local_path = self.image_map.get(src)
            if local_path:
                return f'#image("{local_path}", height: 1.2em)'
            return ""
        elif name == "br":
            return " " if self.in_table else " \\"
        elif name == "sup":
            text = self._get_text(tag).strip()
            return f"#super[{self._escape(text)}]" if text else ""
        elif name == "sub":
            text = self._get_text(tag).strip()
            return f"#sub[{self._escape(text)}]" if text else ""
        elif name == "span":
            classes = tag.get("class") or []
            # Check for note blocks
            if "note" in classes:
                content = self._inline_content(tag).strip()
                if content:
                    if "note-warning" in classes:
                        return f"\n#warning-box[{content}]\n"
                    return f"\n#note-box[{content}]\n"
                return ""
            # Check CSS color classes (e.g. text-green, text-red)
            color = None
            for cls in classes:
                color = _TEXT_COLOR_CLASSES.get(cls)
                if color:
                    break
            # Fall back to inline style color
            if not color:
                style = tag.get("style") or ""
                color = self._extract_text_color(style)
            content = self._inline_content(tag)
            if color:
                return f'#text(fill: rgb("{color}"))[{content}]'
            return content
        elif name == "div":
            classes = tag.get("class") or []
            if "thumb" in classes:
                img = tag.find("img")
                if img:
                    src = img.get("src", "")
                    local_path = self.image_map.get(src)
                    if local_path:
                        return f'#image("{local_path}", width: 60%)'
                return ""
            if any("mw-highlight" in c for c in classes):
                pre = tag.find("pre")
                if pre:
                    code = pre.get_text().rstrip()
                    return f"\n```\n{code}\n```\n"
            return self._inline_content(tag)
        elif name in ("ul", "ol"):
            marker = "+" if name == "ol" else "-"
            items = []
            for li in tag.find_all("li", recursive=False):
                item = self._inline_content(li).strip()
                if item:
                    items.append(f"{marker} {item}")
            return "\n" + "\n".join(items) + "\n"
        elif name == "pre":
            code = tag.get_text().rstrip()
            return f"\n```\n{code}\n```\n"
        elif name == "table":
            return ""
        else:
            return self._inline_content(tag)

    # --- Utilities ---

    def _get_text(self, node) -> str:
        if isinstance(node, NavigableString):
            return str(node)
        if isinstance(node, Tag):
            return node.get_text()
        return ""

    def _escape(self, text: str) -> str:
        if not text:
            return text
        return text.translate(_ESCAPE_TABLE)

    def _extract_bg_color(self, node: Tag) -> str | None:
        style = node.get("style") or ""
        m = _RE_BG_HEX.search(style)
        if m:
            return m.group(1)
        m = _RE_BG_NAMED.search(style)
        if m:
            return _NAMED_COLORS.get(m.group(1).lower())
        return None

    def _extract_text_color(self, style: str) -> str | None:
        m = _RE_TEXT_COLOR.search(style)
        if m:
            return m.group(1)
        return None
