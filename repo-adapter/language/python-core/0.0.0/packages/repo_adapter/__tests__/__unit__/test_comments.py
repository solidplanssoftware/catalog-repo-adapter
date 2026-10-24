"""Which comments the core reads out of a Python file, decoded as Python decodes it."""

from __future__ import annotations

from pathlib import Path

from repo_adapter.command_adapter.comments_command_adapter import extract_comments


def test_a_comment_is_answered_with_its_line(tmp_path: Path) -> None:
    source = tmp_path / "a.py"
    source.write_text("x = 1  # TODO: one\n\n# two\n", encoding="utf-8")

    assert extract_comments(path=source) == [(1, "TODO: one"), (3, "two")]


def test_a_file_declaring_its_encoding_is_read_in_it(tmp_path: Path) -> None:
    """A coding comment is Python's own declaration, so it decides the text."""
    source = tmp_path / "latin.py"
    source.write_bytes("# -*- coding: latin-1 -*-\n# café\n".encode("latin-1"))

    assert extract_comments(path=source)[1] == (2, "café")


def test_a_file_that_is_no_python_answers_nothing(tmp_path: Path) -> None:
    source = tmp_path / "notes.txt"
    source.write_text("# a heading\n", encoding="utf-8")

    assert extract_comments(path=source) == []
