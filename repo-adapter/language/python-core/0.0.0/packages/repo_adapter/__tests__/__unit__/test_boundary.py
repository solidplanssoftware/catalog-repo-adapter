"""What the adapter reads out of a module's two boundary files.

Which file each boundary is, what it imports and what it exports are the
language's to read; whether an export passes a symbol straight through is the
caller's to judge, so what is held here is the reading.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

from repo_adapter.__tests__.python_adapter import adapter

_PACKAGES = {
    "parent": "parent",
    "parent.src.child": "child",
    "parent.src.other": "other",
    "helper": "helper",
}


def _write(*, path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _module(*, name: str, root: str) -> Any:
    return SimpleNamespace(name=name, rootDir=root)


def test_a_facade_answers_with_everything_it_imports(tmp_path: Path) -> None:
    """Its own submodules, other packages, and what it imports only to annotate."""
    _write(
        path=tmp_path / "parent" / "submodule_api.py",
        content=(
            "from typing import TYPE_CHECKING\n"
            "import helper\n"
            "from parent.src.child import thing\n"
            "from .src import other\n"
            "from parent.config import own\n"
            "if TYPE_CHECKING:\n"
            "    from parent.src.later import Later\n"
        ),
    )

    answer = adapter.read_boundary(
        module=_module(name="parent", root="parent"),
        repo_root=tmp_path,
        module_by_package={**_PACKAGES, "parent.src.later": "later"},
        boundary="facade",
    )

    assert answer is not None
    assert answer.path == Path("parent") / "submodule_api.py"
    # Never the module itself: its own files changing is already known.
    assert answer.imports == {"helper", "child", "other", "later"}


def test_a_module_with_no_such_file_answers_none(tmp_path: Path) -> None:
    _write(path=tmp_path / "parent" / "__init__.py", content="import helper\n")

    for boundary in ("facade", "exports"):
        assert (
            adapter.read_boundary(
                module=_module(name="parent", root="parent"),
                repo_root=tmp_path,
                module_by_package=_PACKAGES,
                boundary=boundary,
            )
            is None
        )


def test_an_export_says_where_it_comes_from_only_when_that_is_elsewhere(
    tmp_path: Path,
) -> None:
    """Imported absolutely: its module. Defined here or taken from inside: none."""
    _write(
        path=tmp_path / "parent" / "external_api.py",
        content=(
            "from helper.tools import Passed\n"
            "from parent.src.child import Child\n"
            "from .src.other import Inside\n"
            "from helper import Redone\n"
            "class Redone:\n"
            "    pass\n"
            "def made() -> None:\n"
            "    pass\n"
            "__all__ = ('Passed', 'Child', 'Inside', 'Redone', 'made')\n"
        ),
    )

    answer = adapter.read_boundary(
        module=_module(name="parent", root="parent"),
        repo_root=tmp_path,
        module_by_package=_PACKAGES,
        boundary="exports",
    )

    assert answer is not None
    assert answer.path == Path("parent") / "external_api.py"
    assert [(e.name, e.source, e.line) for e in answer.exports] == [
        ("Passed", "helper", 1),
        ("Child", "child", 2),
        ("Inside", None, 3),
        ("Redone", None, 0),
        ("made", None, 0),
    ]
