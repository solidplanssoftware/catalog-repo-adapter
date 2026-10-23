"""Extract raw comment text from Python source files."""

from __future__ import annotations

import re
import tokenize
from pathlib import Path


def extract_comments(*, path: Path) -> list[tuple[int, str]]:
    """Extract raw comment text from Python source files.

    Supports:
    - Python files (*.py, *.pyi): lines with # comments

    Returns ``(line_number, comment)`` pairs: the 1-based line the comment sits
    on, and the text after the # marker with leading/trailing whitespace
    trimmed. Returns empty list if the file is not a Python file or cannot be
    read. The file is decoded as Python decodes it, by its coding comment or
    byte-order mark and UTF-8 otherwise, which is why the contract hands the
    path rather than text a caller decoded.
    """
    python_extensions = (".py", ".pyi")

    if path.suffix.lower() not in python_extensions:
        return []

    try:
        with tokenize.open(path) as source:
            text = source.read()
    except (OSError, UnicodeDecodeError, SyntaxError):
        return []

    comments: list[tuple[int, str]] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        # Match # comments: line-start (with leading whitespace) or inline.
        match = re.search(
            r"(?:"
            r"^[ \t]*#"  # # at line start (with leading whitespace)
            r"|(?<!\w)#(?!#)"  # # inline (word boundary before, not ##)
            r")"
            r"(.*)$",
            line,
        )
        if match:
            comment_text = match.group(1).strip()
            if comment_text:
                comments.append((line_number, comment_text))

    return comments
