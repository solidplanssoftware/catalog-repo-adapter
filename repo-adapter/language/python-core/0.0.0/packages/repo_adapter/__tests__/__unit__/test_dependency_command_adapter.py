from __future__ import annotations

from pathlib import Path

from repo_adapter_api import all_test_patterns

from repo_adapter.__tests__.python_adapter import adapter
from repo_adapter.command_adapter.dependency_command_adapter import dep_groups

# Mirrors the shape that broke: a parent module whose root directory
# encloses its submodules, one of which is a plain package beside loose
# parent-owned files.
_PACKAGES = {
    "parent": "parent",
    "parent.src.child": "child",
    "parent.src.other": "other",
    "helper": "helper",
}


def _write(*, path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _detect(*, tmp_path: Path, name: str, root: str) -> set[str]:
    groups = dep_groups(
        module={"rootDir": root, "name": name},
        repo_root=tmp_path,
        module_by_package=_PACKAGES,
        non_source_patterns=adapter.non_source_patterns(),
        test_patterns=all_test_patterns(adapter=adapter, repo_root=tmp_path),
    )
    return groups.detected


def test_a_parent_is_not_credited_with_its_submodules_imports(tmp_path: Path) -> None:
    """Each file is scanned by exactly the module that owns it: a parent
    whose root directory encloses a submodule used to collect that
    submodule's imports as its own."""
    _write(path=tmp_path / "parent" / "src" / "loose.py", content="import helper\n")
    _write(
        path=tmp_path / "parent" / "src" / "child" / "__init__.py",
        content="import helper\n",
    )

    assert _detect(tmp_path=tmp_path, name="parent", root="parent") == {"helper"}
    assert _detect(tmp_path=tmp_path, name="child", root="parent/src/child") == {
        "helper"
    }


def test_a_relative_sibling_import_names_the_sibling(tmp_path: Path) -> None:
    """`from .. import other` names the sibling module, not whichever
    module happens to own the bare package directory."""
    _write(
        path=tmp_path / "parent" / "src" / "child" / "__init__.py",
        content="from .. import other\n",
    )

    assert _detect(tmp_path=tmp_path, name="child", root="parent/src/child") == {
        "other"
    }


def test_every_alias_of_one_import_is_resolved(tmp_path: Path) -> None:
    """`from .. import a, b` names two modules; resolving only the
    first match lost the rest."""
    _write(
        path=tmp_path / "parent" / "src" / "child" / "__init__.py",
        content="from .. import other, loose\n",
    )

    # `other` is a module; `loose` resolves through the parent package.
    assert _detect(tmp_path=tmp_path, name="child", root="parent/src/child") == {
        "other",
        "parent",
    }


def test_a_symbol_import_still_names_its_module(tmp_path: Path) -> None:
    _write(
        path=tmp_path / "parent" / "src" / "child" / "__init__.py",
        content="from parent.src.other import something\n",
    )

    assert _detect(tmp_path=tmp_path, name="child", root="parent/src/child") == {
        "other"
    }


def test_a_self_import_is_not_a_dependency(tmp_path: Path) -> None:
    _write(
        path=tmp_path / "parent" / "src" / "child" / "__init__.py",
        content="from .part import piece\n",
    )
    _write(
        path=tmp_path / "parent" / "src" / "child" / "part.py", content="piece = 1\n"
    )

    assert _detect(tmp_path=tmp_path, name="child", root="parent/src/child") == set()


def test_an_environment_inside_the_tree_is_not_scanned(tmp_path: Path) -> None:
    """A virtualenv's site-packages import the world; crediting the
    module that contains the venv with those imports invented edges
    the module's own code never had."""
    _write(path=tmp_path / "parent" / "src" / "loose.py", content="import helper\n")
    _write(
        path=tmp_path / "parent" / ".venv" / "Lib" / "site-packages" / "pkg.py",
        content="import other\n",
    )
    _write(path=tmp_path / "parent" / "build" / "out.py", content="import other\n")

    assert _detect(tmp_path=tmp_path, name="parent", root="parent") == {"helper"}


def test_a_type_checking_import_is_a_dev_dependency(tmp_path: Path) -> None:
    """An import under `if TYPE_CHECKING:` never runs; recording it as
    a runtime edge manufactured cycles out of annotations."""
    _write(
        path=tmp_path / "parent" / "src" / "child" / "__init__.py",
        content="from typing import TYPE_CHECKING\n"
        "import helper\n"
        "if TYPE_CHECKING:\n"
        "    from parent.src.other import something\n",
    )
    groups = dep_groups(
        module={"rootDir": "parent/src/child", "name": "child"},  # type: ignore[typeddict-item]
        repo_root=tmp_path,
        module_by_package=_PACKAGES,
        non_source_patterns=adapter.non_source_patterns(),
        test_patterns=all_test_patterns(adapter=adapter, repo_root=tmp_path),
    )
    assert groups.detected == {"helper"}
    assert groups.detected_dev == {"other"}


def test_a_single_file_module_is_scanned(tmp_path: Path) -> None:
    """A module root may name one file rather than a directory.

    Walking a file yields nothing, so a module declared that way would
    report no dependencies at all -- and its imports would look like the
    enclosing module's.
    """
    _write(path=tmp_path / "parent" / "src" / "loose.py", content="import helper\n")
    _write(path=tmp_path / "parent" / "src" / "solo.py", content="import helper\n")

    packages = {**_PACKAGES, "parent.src.solo": "solo"}
    groups = dep_groups(
        module={"rootDir": "parent/src/solo.py", "name": "solo"},
        repo_root=tmp_path,
        module_by_package=packages,
        non_source_patterns=adapter.non_source_patterns(),
        test_patterns=all_test_patterns(adapter=adapter, repo_root=tmp_path),
    )

    assert groups.detected == {"helper"}
