"""Whether an unpacked package holds every module it imports from itself.

What was measured: a publish carried an edited `__init__.py` and not the new
module it imported, and every consumer met `ModuleNotFoundError` from its own
`lib/`, long after the publish. These tests build that tree and its near
relatives and ask the adapter about them without importing anything.
"""

from __future__ import annotations

from pathlib import Path

from repo_adapter.__tests__.python_adapter import adapter


def _package(*, root: Path, files: dict[str, str]) -> Path:
    """A package tree at `root/widget`, one file per entry."""
    package = root / "widget"
    for relative, content in files.items():
        path = package / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return package


def _unresolved(*, package: Path) -> list[str]:
    return list(
        adapter.unresolved_package_imports(package_root=package, package_name="widget")
    )


def test_a_relative_import_of_a_module_the_tree_lacks_is_named(tmp_path: Path) -> None:
    """The measured case: the edited file arrived and the new module did not."""
    package = _package(
        root=tmp_path,
        files={
            "__init__.py": "from .src.arg_shadowing import *\n",
            "src/__init__.py": "",
            "src/arg_shadowing/__init__.py": "from .naming import shadowed_name\n",
        },
    )

    assert _unresolved(package=package) == [
        "src/arg_shadowing/__init__.py: widget.src.arg_shadowing.naming"
    ]


def test_an_absolute_import_of_the_package_is_checked_too(tmp_path: Path) -> None:
    package = _package(
        root=tmp_path,
        files={"__init__.py": "", "inner/__init__.py": "import widget.inner.gone\n"},
    )

    assert _unresolved(package=package) == ["inner/__init__.py: widget.inner.gone"]


def test_a_name_that_is_neither_a_submodule_nor_bound_is_named(tmp_path: Path) -> None:
    """`from . import naming` is the same missing module spelled another way."""
    package = _package(
        root=tmp_path,
        files={
            "__init__.py": "VALUE = 1\n",
            "consumer.py": "from . import naming\nfrom . import VALUE\n",
        },
    )

    assert _unresolved(package=package) == ["consumer.py: widget.naming"]


def test_a_complete_tree_and_other_packages_report_nothing(tmp_path: Path) -> None:
    """Every import resolves, and a third-party one is not this tree's question."""
    package = _package(
        root=tmp_path,
        files={
            "__init__.py": "from .helper import help_me\nfrom . import helper\n",
            "helper.py": "import yaml\nfrom pydantic import BaseModel\n",
            "ns/leaf.py": "from widget.ns import leaf\n",
        },
    )

    assert _unresolved(package=package) == []


def test_an_import_its_author_allowed_to_be_absent_is_not_reported(
    tmp_path: Path,
) -> None:
    package = _package(
        root=tmp_path,
        files={
            "__init__.py": (
                "try:\n"
                "    from .optional import extra\n"
                "except ImportError:\n"
                "    extra = None\n"
            ),
        },
    )

    assert _unresolved(package=package) == []


def test_a_tree_with_no_python_answers_nothing(tmp_path: Path) -> None:
    """The shared documents are vendored the same way and hold no Python."""
    package = _package(
        root=tmp_path, files={"instructions/workflow.md": "# Workflow\n"}
    )

    assert _unresolved(package=package) == []
