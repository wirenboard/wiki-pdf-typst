"""Typst compilation wrapper."""

import os
import re
import subprocess


TYPST_BIN = os.path.join(os.path.dirname(os.path.dirname(__file__)), "bin", "typst")
FONT_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "fonts")


def compile(input_typ: str, output_pdf: str) -> str:
    """Compile a .typ file to PDF, auto-fixing colspan errors.

    Returns the path to the output PDF.
    Raises RuntimeError on compilation failure.
    """
    cmd = [TYPST_BIN, "compile", input_typ, output_pdf]
    if os.path.isdir(FONT_PATH):
        cmd.extend(["--font-path", FONT_PATH])

    for attempt in range(15):
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            return output_pdf

        # Auto-fix: reduce all overflowing colspans by 1
        if ("colspan would cause" in result.stderr or "would span a previously" in result.stderr) and attempt < 14:
            error_lines = set()
            for m in re.finditer(r"(\d+) .*table\.cell\(colspan: (\d+)\)", result.stderr):
                error_lines.add(int(m.group(1)))

            if error_lines:
                with open(input_typ, "r") as f:
                    lines = f.readlines()
                for ln in error_lines:
                    if 0 < ln <= len(lines):
                        lines[ln - 1] = re.sub(
                            r"colspan: (\d+)",
                            lambda m: f"colspan: {max(1, int(m.group(1)) - 1)}",
                            lines[ln - 1],
                        )
                with open(input_typ, "w") as f:
                    f.writelines(lines)
                continue

        raise RuntimeError(f"Typst compilation failed:\n{result.stderr}")
    raise RuntimeError("Typst compilation failed after retries")
