"""Typst compilation wrapper."""

import os
import subprocess


TYPST_BIN = os.path.join(os.path.dirname(os.path.dirname(__file__)), "bin", "typst")
FONT_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "fonts")


def compile(input_typ: str, output_pdf: str) -> str:
    """Compile a .typ file to PDF.

    Returns the path to the output PDF.
    Raises RuntimeError on compilation failure.
    """
    cmd = [TYPST_BIN, "compile", input_typ, output_pdf]
    if os.path.isdir(FONT_PATH):
        cmd.extend(["--font-path", FONT_PATH])
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Typst compilation failed:\n{result.stderr}")
    return output_pdf
