"""Typst compilation wrapper."""

import os
import re
import subprocess


TYPST_BIN = os.path.join(os.path.dirname(os.path.dirname(__file__)), "bin", "typst")
FONT_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "fonts")

_RE_COLSPAN_LINE = re.compile(r"(\d+) .*table\.cell\(colspan: (\d+)\)")


def compile(input_typ: str, output_pdf: str) -> str:
    """Compile a .typ file to PDF, auto-fixing colspan/rowspan errors.

    Returns the path to the output PDF.
    Raises RuntimeError on compilation failure.
    """
    cmd = [TYPST_BIN, "compile", input_typ, output_pdf]
    if os.path.isdir(FONT_PATH):
        cmd.extend(["--font-path", FONT_PATH])

    for attempt in range(20):
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            return output_pdf

        is_colspan_err = "colspan would cause" in result.stderr
        is_overlap_err = "would span a previously" in result.stderr
        if (is_colspan_err or is_overlap_err) and attempt < 19:
            error_lines = {}
            for m in _RE_COLSPAN_LINE.finditer(result.stderr):
                error_lines[int(m.group(1))] = int(m.group(2))

            if error_lines:
                with open(input_typ, "r") as f:
                    lines = f.readlines()
                for ln, old_cs in error_lines.items():
                    if 0 < ln <= len(lines):
                        if is_overlap_err:
                            # Strip colspan entirely for overlap conflicts
                            lines[ln - 1] = re.sub(
                                r"table\.cell\(colspan: \d+\)",
                                "table.cell()",
                                lines[ln - 1],
                            )
                        else:
                            # Reduce by half (faster convergence than -1)
                            new_cs = max(1, old_cs // 2)
                            lines[ln - 1] = lines[ln - 1].replace(
                                f"colspan: {old_cs}", f"colspan: {new_cs}", 1
                            )
                with open(input_typ, "w") as f:
                    f.writelines(lines)
                continue

        raise RuntimeError(f"Typst compilation failed:\n{result.stderr}")
    raise RuntimeError("Typst compilation failed after retries")
