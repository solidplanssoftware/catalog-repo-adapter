"""What this adapter answers about the shape of a Python tree."""

from __future__ import annotations

from pathlib import Path

import pytest
from repo_adapter_api import (
    PathSource,
    all_non_source_patterns,
    is_non_source,
    unserved_language_version,
)

from repo_adapter.__tests__.python_adapter import adapter


def test_a_directory_with_an_init_is_a_package_named_by_its_path(
    tmp_path: Path,
) -> None:
    package = tmp_path / "app" / "src" / "registry"
    for directory in (tmp_path / "app", tmp_path / "app" / "src", package):
        directory.mkdir()
        (directory / "__init__.py").write_text("", encoding="utf-8")

    assert (
        adapter.resolve_package_name(directory=package, repo_root=tmp_path)
        == "app.src.registry"
    )


def test_a_package_is_named_from_the_nearest_directory_that_is_not_one(
    tmp_path: Path,
) -> None:
    """A `src/` layout no build backend was told about is still named as imported.

    Only setuptools' `where` is read as a declaration. flit, hatchling and
    the rest find `src/` for themselves, so the repository states nothing,
    and counted from its root the package was `src.itsdangerous`.
    """
    (tmp_path / "pyproject.toml").write_text(
        '[build-system]\nbuild-backend = "flit_core.buildapi"\n', encoding="utf-8"
    )
    package = tmp_path / "src" / "itsdangerous"
    nested = package / "codec"
    nested.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    (nested / "__init__.py").write_text("", encoding="utf-8")

    assert (
        adapter.resolve_package_name(directory=package, repo_root=tmp_path)
        == "itsdangerous"
    )
    assert (
        adapter.resolve_package_name(directory=nested, repo_root=tmp_path)
        == "itsdangerous.codec"
    )


def test_a_directory_without_one_is_no_package(tmp_path: Path) -> None:
    """A namespace portion has no single directory to hand a packager."""
    directory = tmp_path / "app" / "src" / "registry"
    directory.mkdir(parents=True)

    assert adapter.resolve_package_name(directory=directory, repo_root=tmp_path) is None


def test_the_repository_root_is_not_a_package(tmp_path: Path) -> None:
    """It has no name relative to itself, whatever it carries."""
    (tmp_path / "__init__.py").write_text("", encoding="utf-8")

    assert adapter.resolve_package_name(directory=tmp_path, repo_root=tmp_path) is None


def test_what_holds_no_python_is_named(tmp_path: Path) -> None:
    """A cache, an installed environment, a fetched dependency tree, a build."""
    del tmp_path

    patterns = all_non_source_patterns(patterns=adapter.non_source_patterns())

    for directory in [".venv", "node_modules", "build", "dist", "lib"]:
        assert is_non_source(relative_path=directory, patterns=patterns), directory
    assert is_non_source(relative_path="a/b/__pycache__", patterns=patterns)


def test_a_name_a_build_writes_is_skipped_at_the_root_alone(tmp_path: Path) -> None:
    """`build` is where a build writes, and equally a command package's name.

    One list read two ways rather than two lists: the same answer has to hide
    the directory a build writes at the module root and leave a package called
    `build` further down alone, and only the rooted reading tells them apart.
    Read loosely -- which is what the dependency scan did with a list of its
    own -- dev-tool's whole `registry/app/build/` went unscanned.
    """
    del tmp_path

    patterns = all_non_source_patterns(patterns=adapter.non_source_patterns())

    assert is_non_source(relative_path="build/lib/pkg", patterns=patterns)
    assert not is_non_source(relative_path="src/registry/app/build", patterns=patterns)
    # A cache is the other way round, and is why one reading would not do.
    assert is_non_source(
        relative_path="src/registry/app/__pycache__", patterns=patterns
    )


def test_a_test_package_is_named_wherever_it_sits(tmp_path: Path) -> None:
    """Tests live beside the code they cover, so there is no one place to root.

    Read the way the non-source list is, and answering a different question:
    these directories are source, and are what an application built from the
    tree does not contain.
    """
    del tmp_path

    names = adapter.test_directories()

    assert is_non_source(relative_path="__tests__", patterns=names)
    assert is_non_source(relative_path="src/registry/app/__tests__", patterns=names)
    assert not is_non_source(relative_path="src/registry/app/build", patterns=names)
    assert not is_non_source(
        relative_path="src/registry/__tests__", patterns=adapter.non_source_patterns()
    )


def test_package_data_is_read_from_the_packaging_metadata(tmp_path: Path) -> None:
    """Where a Python repository already states it, so it is not restated."""
    (tmp_path / "manifest").mkdir()
    (tmp_path / "manifest" / "schema.yml").write_text("name: t", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        '[tool.setuptools.package-data]\n"manifest" = ["schema.yml"]\n',
        encoding="utf-8",
    )

    declared = adapter.declared_package_data(repo_root=tmp_path)

    assert [entry.source for entry in declared] == [
        tmp_path / "manifest" / "schema.yml"
    ]
    assert [entry.destination for entry in declared] == ["manifest"]


def test_package_data_is_found_and_counted_from_where_packages_are_declared(
    tmp_path: Path,
) -> None:
    """`packages/app/app.yml` is read by the code beside it as `app/app.yml`.

    Looked for under the repository root it was found nowhere, once a
    repository's package sat under `packages/` rather than at its root.
    """
    (tmp_path / "packages" / "app").mkdir(parents=True)
    (tmp_path / "packages" / "app" / "app.yml").write_text("name: t", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        '[tool.setuptools.packages.find]\nwhere = ["packages"]\n'
        '[tool.setuptools.package-data]\n"app" = ["*.yml"]\n',
        encoding="utf-8",
    )

    declared = adapter.declared_package_data(repo_root=tmp_path)

    assert [entry.source for entry in declared] == [
        tmp_path / "packages" / "app" / "app.yml"
    ]
    assert [entry.destination for entry in declared] == ["app"]


def test_a_tree_with_no_packaging_metadata_declares_none(tmp_path: Path) -> None:
    assert adapter.declared_package_data(repo_root=tmp_path) == []


def test_the_generated_requirements_file_is_sorted_and_holds_each_once(
    tmp_path: Path,
) -> None:
    """A generated file is a function of what was fetched, not of its order.

    Two producers naming one package, and the same package reached twice by
    two paths through a closure, are one line -- otherwise the file moves
    whenever the walk does and no diff of it means anything.
    """
    rendered = adapter.render_vendored_requirements(
        repo_root=tmp_path,
        requirements=["tzdata>=2025.1", "PyYAML>=6.0.2", "tzdata>=2025.1"],
    )

    assert rendered is not None
    assert Path(str(rendered.path)) == Path("__req__/vendored-requirements.txt")
    stated = [
        line
        for line in rendered.content.splitlines()
        if line and not line.startswith("#")
    ]
    assert stated == ["PyYAML>=6.0.2", "tzdata>=2025.1"]


def test_the_generated_file_says_it_is_generated(tmp_path: Path) -> None:
    """It is committed, so it is read in a diff before it is read anywhere else."""
    rendered = adapter.render_vendored_requirements(repo_root=tmp_path, requirements=[])

    assert rendered is not None
    assert rendered.content.splitlines()[0].startswith("# Generated by")


def test_a_repository_that_vendored_nothing_still_gets_a_file(tmp_path: Path) -> None:
    """*These trees need nothing installed* is a statement, and an absent file
    is packaging metadata that refuses to build in a clone that has not
    vendored yet."""
    rendered = adapter.render_vendored_requirements(repo_root=tmp_path, requirements=[])

    assert rendered is not None
    assert not [
        line
        for line in rendered.content.splitlines()
        if line and not line.startswith("#")
    ]


def test_requirements_declared_through_dynamic_are_read(tmp_path: Path) -> None:
    """A repository that vendors cannot write `dependencies` out in full.

    Half of it is what its own code needs and half is what the trees it
    fetched need, which nobody types -- so both halves move into files and the
    pyproject names them. A reader that only knew the inline list saw a
    repository declaring nothing at all.
    """
    (tmp_path / "pyproject.toml").write_text(
        "[project]\n"
        'name = "consumer"\n'
        'dynamic = ["dependencies"]\n'
        "[tool.setuptools.dynamic]\n"
        'dependencies = { file = ["requirements.txt", "__req__/vendored-requirements.txt"] }\n',
        encoding="utf-8",
    )
    (tmp_path / "requirements.txt").write_text(
        "# what this repository's own code needs\npydantic==2.8.2\n", encoding="utf-8"
    )
    (tmp_path / "__req__").mkdir()
    (tmp_path / "__req__" / "vendored-requirements.txt").write_text(
        "# Generated by `dev vendor`. Do not edit.\ntzdata>=2025.1\n", encoding="utf-8"
    )

    assert adapter.declared_language_requirements(
        repo_root=tmp_path, include_development=True
    ) == ["pydantic==2.8.2", "tzdata>=2025.1"]


def test_a_publisher_does_not_claim_what_it_only_carries(tmp_path: Path) -> None:
    """The generated file holds what somebody else's source needs.

    It is on its way to an installer, not part of what this repository states
    about itself -- so a publisher recording what a consumer of *its* package
    must have installed leaves it out, and a consumer asking whether its own
    environment is complete counts it.
    """
    (tmp_path / "pyproject.toml").write_text(
        "[project]\n"
        'name = "consumer"\n'
        'dynamic = ["dependencies"]\n'
        "[tool.setuptools.dynamic]\n"
        'dependencies = { file = ["requirements.txt", "__req__/vendored-requirements.txt"] }\n',
        encoding="utf-8",
    )
    (tmp_path / "requirements.txt").write_text("pydantic==2.8.2\n", encoding="utf-8")
    (tmp_path / "__req__").mkdir()
    (tmp_path / "__req__" / "vendored-requirements.txt").write_text(
        "tzdata>=2025.1\n", encoding="utf-8"
    )

    assert adapter.declared_language_requirements(repo_root=tmp_path) == [
        "pydantic==2.8.2"
    ]


def test_an_installer_option_is_not_a_requirement(tmp_path: Path) -> None:
    """`-r`, an index url, a flag: read as a package, none could ever match."""
    (tmp_path / "pyproject.toml").write_text(
        "[project]\n"
        'name = "consumer"\n'
        'dynamic = ["dependencies"]\n'
        "[tool.setuptools.dynamic]\n"
        'dependencies = { file = ["requirements.txt"] }\n',
        encoding="utf-8",
    )
    (tmp_path / "requirements.txt").write_text(
        "--index-url https://example.invalid/simple\n"
        "-r other.txt\n"
        "\n"
        "pydantic==2.8.2  # pinned\n",
        encoding="utf-8",
    )

    assert adapter.declared_language_requirements(repo_root=tmp_path) == [
        "pydantic==2.8.2"
    ]


def test_a_source_naming_a_path_is_a_path_source(tmp_path: Path) -> None:
    """Only a path is coupling: a git url and an index resolve without a checkout."""
    (tmp_path / "pyproject.toml").write_text(
        "\n".join(
            [
                "[tool.uv.sources]",
                'config = { path = "config", editable = true }',
                'remote = { git = "https://example.invalid/remote.git" }',
                'indexed = { index = "internal" }',
                "sibling = [",
                '  { path = "../sibling", marker = "sys_platform == \'win32\'" },',
                '  { git = "https://example.invalid/sibling.git" },',
                "]",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    assert adapter.declared_path_sources(repo_root=tmp_path) == [
        PathSource(package="config", path="config"),
        PathSource(package="sibling", path="../sibling"),
    ]


def test_a_repository_without_packaging_declares_no_path_source(tmp_path: Path) -> None:
    assert adapter.declared_path_sources(repo_root=tmp_path) == []


def test_unreadable_packaging_declares_no_path_source(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[tool.uv.sources\n", encoding="utf-8")

    assert adapter.declared_path_sources(repo_root=tmp_path) == []


def _requiring(*, tmp_path: Path, stated: str) -> str | None:
    (tmp_path / "pyproject.toml").write_text(
        f'[project]\nname = "a"\nrequires-python = "{stated}"\n', encoding="utf-8"
    )
    return adapter.language_version(repo_root=tmp_path)


@pytest.mark.parametrize(
    ("stated", "lowest"),
    [
        (">=3.13", "3.13"),
        (">= 3.13, <4", "3.13"),
        ("<3.15,>=3.12.4", "3.12.4"),
        ("~=3.13", "3.13"),
        ("==3.13.*", "3.13"),
        ("==3.14.1", "3.14.1"),
        # Each has to hold, so the highest floor is the lowest version admitted.
        (">=3.11,>=3.13", "3.13"),
        (">=3.9,>=3.13", "3.13"),
        # Read no further than a patch, which is as far as a range is written.
        (">=3.13.0.1", "3.13.0"),
    ],
)
def test_the_language_version_is_the_lowest_the_repository_admits(
    tmp_path: Path, stated: str, lowest: str
) -> None:
    assert _requiring(tmp_path=tmp_path, stated=stated) == lowest


@pytest.mark.parametrize("stated", ["<4", ">3.12", "!=3.12.*", "", "python3"])
def test_a_statement_setting_no_floor_names_no_version(
    tmp_path: Path, stated: str
) -> None:
    assert _requiring(tmp_path=tmp_path, stated=stated) is None


def test_a_repository_stating_no_python_names_no_version(tmp_path: Path) -> None:
    assert adapter.language_version(repo_root=tmp_path) is None

    (tmp_path / "pyproject.toml").write_text('[project]\nname = "a"\n', "utf-8")
    assert adapter.language_version(repo_root=tmp_path) is None

    (tmp_path / "pyproject.toml").write_text("[project\n", encoding="utf-8")
    assert adapter.language_version(repo_root=tmp_path) is None


def test_the_core_is_for_the_version_its_own_repository_states() -> None:
    """What the core says it is for holds the repository it is developed in."""
    own_root = Path(__file__).resolve().parents[4]

    assert adapter.languageVersions == ["3.9", "3.14"]
    assert unserved_language_version(adapter=adapter, repo_root=own_root) is None
