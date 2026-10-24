"""What generated code imports ``TypeBase`` from, per schema owner."""

from __future__ import annotations

from pathlib import Path

from repo_adapter.__tests__.python_adapter import adapter


def _write_pyproject(*, repo_root: Path, body: str) -> None:
    repo_root.mkdir(parents=True, exist_ok=True)
    (repo_root / "pyproject.toml").write_text(body, encoding="utf-8")


def test_no_ancestor_binds_the_runtime_directly() -> None:
    """A schema no module owns, or a top-level module's own, imports `type`."""
    assert (
        adapter.resolve_type_runtime_binding(
            submodule_ancestor_root=None, repo_root=Path("/tmp/anywhere")
        )
        == "type"
    )


def test_an_ancestor_directory_binds_through_its_facade() -> None:
    """The consumer's view: the ancestor's checkout directory is its package."""
    assert (
        adapter.resolve_type_runtime_binding(
            submodule_ancestor_root=Path("command"), repo_root=Path("/tmp/tree")
        )
        == "command.submodule_api"
    )


def test_the_repository_itself_binds_through_its_declared_package(
    tmp_path: Path,
) -> None:
    """`.` means the repository being generated is the ancestor.

    Read from the packaging declaration rather than the directory name,
    because the two differ wherever a distribution is named with a hyphen --
    `impl-tool` is checked out at `impl-tool` and imported as `impl_tool`.
    """
    _write_pyproject(
        repo_root=tmp_path,
        body='[tool.setuptools]\npackage-dir = { "impl_tool" = "." }\n',
    )

    assert (
        adapter.resolve_type_runtime_binding(
            submodule_ancestor_root=Path("."), repo_root=tmp_path
        )
        == "impl_tool.submodule_api"
    )


def test_a_repository_publishing_two_packages_binds_through_the_one_it_is_named_for(
    tmp_path: Path,
) -> None:
    """Two packages under one wrapper are told apart by the distribution's name.

    pkgmgr publishes its application and the store library beside it. Counting
    directories cannot say which one the repository is, and answering the bare
    runtime for that made generation from inside the repository disagree with
    generation from the tree.
    """
    _write_pyproject(
        repo_root=tmp_path,
        body=(
            '[project]\nname = "pkg-mgr"\n\n'
            '[tool.setuptools.packages.find]\nwhere = ["packages"]\n'
        ),
    )
    for package in ("pkg_mgr", "pkg_mgr_store"):
        (tmp_path / "packages" / package).mkdir(parents=True)
        (tmp_path / "packages" / package / "__init__.py").write_text("")

    assert (
        adapter.resolve_type_runtime_binding(
            submodule_ancestor_root=Path("."), repo_root=tmp_path
        )
        == "pkg_mgr.submodule_api"
    )


def test_two_packages_neither_named_for_the_distribution_bind_the_runtime(
    tmp_path: Path,
) -> None:
    """Without a name that picks one, two packages are still no answer."""
    _write_pyproject(
        repo_root=tmp_path,
        body=(
            '[project]\nname = "tree"\n\n'
            '[tool.setuptools.packages.find]\nwhere = ["packages"]\n'
        ),
    )
    for package in ("first", "second"):
        (tmp_path / "packages" / package).mkdir(parents=True)
        (tmp_path / "packages" / package / "__init__.py").write_text("")

    assert (
        adapter.resolve_type_runtime_binding(
            submodule_ancestor_root=Path("."), repo_root=tmp_path
        )
        == "type"
    )


def test_a_repository_whose_root_is_not_a_package_binds_the_runtime(
    tmp_path: Path,
) -> None:
    """No `package-dir` mapping to `.` is no root package to bind through.

    This is the tree that pins others: its own root is not delivered as a
    package, so a module of its own is answered with the bare runtime exactly
    as it was before `.` meant anything.
    """
    _write_pyproject(
        repo_root=tmp_path,
        body='[project]\nname = "platform"\n\n[tool.setuptools.packages.find]\nwhere = ["."]\n',
    )

    assert (
        adapter.resolve_type_runtime_binding(
            submodule_ancestor_root=Path("."), repo_root=tmp_path
        )
        == "type"
    )


def test_an_unreadable_declaration_binds_the_runtime(tmp_path: Path) -> None:
    """A binding that cannot be resolved is worse than the one that works."""
    _write_pyproject(repo_root=tmp_path, body="[tool.setuptools\nnot toml at all\n")

    assert (
        adapter.resolve_type_runtime_binding(
            submodule_ancestor_root=Path("."), repo_root=tmp_path
        )
        == "type"
    )


def test_no_repository_root_binds_the_runtime() -> None:
    """`generate_types` resolves its own fallback without a repository."""
    assert (
        adapter.resolve_type_runtime_binding(
            submodule_ancestor_root=Path("."), repo_root=None
        )
        == "type"
    )
