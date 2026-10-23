"""Which files of a Python repository are tests, and what detection does with them.

A test file was a file under `__tests__`, spelled where the dependency scan
read it, and that is one tree's layout. A repository keeping its tests in
`tests/`, or as `test_*.py` beside the code, had none of them recognised:
every import its tests made was detected as a runtime dependency, so its
manifest's `testDependencies` were reported wrong and its test framework was
asked for as a runtime edge.

So the adapter answers it, as patterns, and the scan asks the same answer
every caller across the contract gets. Each layout below is a fixture
repository in which an import made only by a test is a test dependency and
nothing else.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from repo_adapter_api import (
    DependencyGroups,
    ManifestModule,
    all_non_source_patterns,
    all_test_patterns,
    is_non_source,
    is_test_file,
)

from repo_adapter.__tests__.python_adapter import adapter

_PACKAGES = {
    "app": "app",
    "helper": "helper",
    "framework": "framework",
}


def _write(*, path: Path, content: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _module(*, root: str, entry_point: str = "__init__.py") -> ManifestModule:
    return ManifestModule(
        name="app",
        rootDir=root,
        entryPoint=entry_point,
        repoAdapter="language:python",
        kind="library",
        dependencies=frozenset(),
        devDependencies=frozenset(),
        testDependencies=frozenset(),
        submodules=[],
        parentModule=None,
    )


def _detect(
    *, repo_root: Path, root: str = ".", entry_point: str = "__init__.py"
) -> DependencyGroups:
    return adapter.discover_dependency_groups(
        module=_module(root=root, entry_point=entry_point),
        repo_root=repo_root,
        module_by_package=_PACKAGES,
    )


def _is_test(*, repo_root: Path, path: str) -> bool:
    return is_test_file(
        relative_path=path,
        patterns=all_test_patterns(adapter=adapter, repo_root=repo_root),
    )


def test_tests_in_a_tests_directory_are_test_dependencies(tmp_path: Path) -> None:
    """The most common layout: the package, and `tests/` beside it."""
    _write(path=tmp_path / "app" / "__init__.py", content="import helper\n")
    _write(path=tmp_path / "tests" / "__init__.py")
    _write(path=tmp_path / "tests" / "test_app.py", content="import framework\n")
    # A helper a test imports is a test file though no runner collects it.
    _write(
        path=tmp_path / "tests" / "support" / "data.py", content="import framework\n"
    )

    groups = _detect(repo_root=tmp_path)

    assert groups.detected == {"helper"}
    assert groups.detected_test == {"framework"}
    assert groups.detected_dev == set()


def test_tests_beside_the_code_are_test_dependencies(tmp_path: Path) -> None:
    """`test_*.py` and `*_test.py` in the package, and a `conftest.py`."""
    _write(path=tmp_path / "app" / "__init__.py", content="import helper\n")
    _write(path=tmp_path / "app" / "clock.py")
    _write(path=tmp_path / "app" / "test_clock.py", content="import framework\n")
    _write(path=tmp_path / "app" / "clock_test.py", content="import framework\n")
    _write(path=tmp_path / "app" / "conftest.py", content="import framework\n")

    groups = _detect(repo_root=tmp_path, root="app")

    assert groups.detected == {"helper"}
    assert groups.detected_test == {"framework"}
    assert groups.detected_dev == set()


def test_tests_in_a_tests_package_are_test_dependencies(tmp_path: Path) -> None:
    """This tree's layout, which reads as it did."""
    _write(path=tmp_path / "app" / "__init__.py", content="import helper\n")
    _write(path=tmp_path / "app" / "__tests__" / "__init__.py")
    _write(
        path=tmp_path / "app" / "__tests__" / "test_app.py",
        content="import framework\n",
    )
    _write(
        path=tmp_path / "app" / "src" / "__tests__" / "runner.py",
        content="import framework\n",
    )

    groups = _detect(repo_root=tmp_path, root="app")

    assert groups.detected == {"helper"}
    assert groups.detected_test == {"framework"}
    assert groups.detected_dev == set()


def test_an_import_under_type_checking_in_a_test_is_still_a_test_dependency(
    tmp_path: Path,
) -> None:
    _write(path=tmp_path / "app" / "__init__.py")
    _write(
        path=tmp_path / "tests" / "test_app.py",
        content="from typing import TYPE_CHECKING\n"
        "if TYPE_CHECKING:\n"
        "    import framework\n",
    )

    groups = _detect(repo_root=tmp_path)

    assert groups == DependencyGroups(
        detected=set(), detected_test={"framework"}, detected_dev=set()
    )


def test_the_conventions_are_answered_where_a_repository_states_nothing(
    tmp_path: Path,
) -> None:
    for path in [
        "app/__tests__/anything.py",
        "tests/anything.py",
        "tests/fixtures/case.schema.yml",
        "app/test_clock.py",
        "app/clock_test.py",
        "app/conftest.py",
        "conftest.py",
    ]:
        assert _is_test(repo_root=tmp_path, path=path), path
    for path in [
        "app/clock.py",
        "app/testing.py",
        "app/latest_clock.py",
        "app/contest.py",
        # A package of test support is a library, not a test.
        "app/test/support.py",
        "test/support.py",
    ]:
        assert not _is_test(repo_root=tmp_path, path=path), path


@pytest.mark.parametrize(
    ("name", "content"),
    [
        (
            "pyproject.toml",
            '[tool.pytest.ini_options]\npython_files = ["check_*.py", "*_spec.py"]\n',
        ),
        (
            "pyproject.toml",
            '[tool.pytest.ini_options]\npython_files = "check_*.py *_spec.py"\n',
        ),
        ("pytest.toml", '[pytest]\npython_files = ["check_*.py", "*_spec.py"]\n'),
        (".pytest.toml", '[pytest]\npython_files = ["check_*.py", "*_spec.py"]\n'),
        (
            "pyproject.toml",
            '[tool.pytest]\npython_files = ["check_*.py", "*_spec.py"]\n',
        ),
        ("pytest.ini", "[pytest]\npython_files = check_*.py *_spec.py\n"),
        (".pytest.ini", "[pytest]\npython_files =\n    check_*.py\n    *_spec.py\n"),
        ("tox.ini", "[pytest]\npython_files = check_*.py *_spec.py\n"),
        ("setup.cfg", "[tool:pytest]\npython_files = check_*.py *_spec.py\n"),
    ],
)
def test_a_repository_stating_its_own_test_files_is_read(
    tmp_path: Path, name: str, content: str
) -> None:
    """`python_files` replaces pytest's default, here as it does for pytest."""
    _write(path=tmp_path / name, content=content)

    assert _is_test(repo_root=tmp_path, path="app/check_clock.py")
    assert _is_test(repo_root=tmp_path, path="app/clock_spec.py")
    assert not _is_test(repo_root=tmp_path, path="app/test_clock.py")
    assert not _is_test(repo_root=tmp_path, path="app/clock_test.py")
    # The directories and `conftest.py` are not pytest's to rename.
    assert _is_test(repo_root=tmp_path, path="tests/helper.py")
    assert _is_test(repo_root=tmp_path, path="app/conftest.py")


def test_the_first_file_configuring_pytest_is_the_one_read(tmp_path: Path) -> None:
    """pytest reads one configuration file, and a `pytest.ini` wins by existing."""
    _write(path=tmp_path / "pytest.ini", content="[pytest]\n")
    _write(
        path=tmp_path / "pyproject.toml",
        content='[tool.pytest.ini_options]\npython_files = ["check_*.py"]\n',
    )
    _write(
        path=tmp_path / "setup.cfg", content="[tool:pytest]\npython_files = x_*.py\n"
    )

    assert _is_test(repo_root=tmp_path, path="app/test_clock.py")
    assert not _is_test(repo_root=tmp_path, path="app/check_clock.py")


def test_a_file_that_does_not_configure_pytest_is_passed_over(tmp_path: Path) -> None:
    _write(path=tmp_path / "pyproject.toml", content='[project]\nname = "app"\n')
    _write(path=tmp_path / "tox.ini", content="[tox]\nenvlist = py313\n")
    _write(
        path=tmp_path / "setup.cfg",
        content="[tool:pytest]\npython_files = check_*.py\n",
    )

    assert _is_test(repo_root=tmp_path, path="app/check_clock.py")
    assert not _is_test(repo_root=tmp_path, path="app/test_clock.py")


def test_a_configuration_that_does_not_parse_states_nothing(tmp_path: Path) -> None:
    _write(path=tmp_path / "pyproject.toml", content="[tool.pytest\n")

    assert _is_test(repo_root=tmp_path, path="app/test_clock.py")


def test_where_collection_starts_is_not_what_a_test_is(tmp_path: Path) -> None:
    """`testpaths` names whole packages in this tree, and a source directory
    wherever tests sit beside the code; neither is a directory of tests."""
    _write(
        path=tmp_path / "pyproject.toml",
        content='[tool.pytest.ini_options]\ntestpaths = ["app"]\n',
    )
    _write(path=tmp_path / "app" / "__init__.py", content="import helper\n")
    _write(path=tmp_path / "app" / "test_app.py", content="import framework\n")

    assert not _is_test(repo_root=tmp_path, path="app/clock.py")
    groups = _detect(repo_root=tmp_path, root="app")
    assert groups.detected == {"helper"}
    assert groups.detected_test == {"framework"}


def test_a_modules_declared_entry_point_is_the_module_whatever_it_is_called(
    tmp_path: Path,
) -> None:
    """A test library enters through `test_support.py` and is not a test.

    Its imports are what a consumer of the library needs at run time, and the
    manifest naming the file as the module's entry point is what says so.
    """
    _write(path=tmp_path / "test" / "__init__.py")
    _write(path=tmp_path / "test" / "test_support.py", content="import helper\n")
    _write(path=tmp_path / "test" / "test_other.py", content="import framework\n")

    groups = _detect(repo_root=tmp_path, root="test", entry_point="test_support.py")

    assert groups.detected == {"helper"}
    assert groups.detected_test == {"framework"}


def test_a_module_that_is_one_file_is_not_a_test_by_its_name(tmp_path: Path) -> None:
    _write(path=tmp_path / "tools" / "test_runner.py", content="import helper\n")

    groups = _detect(
        repo_root=tmp_path, root="tools/test_runner.py", entry_point="test_runner.py"
    )

    assert groups.detected == {"helper"}
    assert groups.detected_test == set()


def test_what_git_leaves_untracked_is_what_a_walk_passes_over() -> None:
    """A broken environment and packaging metadata are skipped as git skips them.

    A virtualenv that failed to build is left beside the good one as
    `.venv.broken`, and a walk that entered it read its site-packages as this
    repository's source; packaging metadata is written beside a package. A
    module whose name only starts the same way is source.
    """
    patterns = all_non_source_patterns(patterns=adapter.non_source_patterns())

    assert is_non_source(relative_path=".venv.broken/lib/site.py", patterns=patterns)
    assert is_non_source(relative_path="platform.egg-info/PKG-INFO", patterns=patterns)
    assert not is_non_source(relative_path="pkg/venv_tools.py", patterns=patterns)


def test_a_pytest_toml_is_read_before_a_pytest_ini(tmp_path: Path) -> None:
    """pytest 9 looks for its TOML file first, and it wins by existing."""
    _write(path=tmp_path / "pytest.toml", content="[pytest]\n")
    _write(path=tmp_path / "pytest.ini", content="[pytest]\npython_files = x_*.py\n")

    assert _is_test(repo_root=tmp_path, path="app/test_clock.py")
    assert not _is_test(repo_root=tmp_path, path="app/x_clock.py")


def test_a_module_is_read_by_the_configuration_nearest_it(tmp_path: Path) -> None:
    """A tree detected from its root pins repositories that state their own.

    Read at the root alone, a pinned module was held to the root's
    `python_files` and its own tests were detected as runtime code.
    """
    _write(
        path=tmp_path / "pyproject.toml",
        content='[tool.pytest.ini_options]\npython_files = ["test_*.py"]\n',
    )
    _write(
        path=tmp_path / "pinned" / "pyproject.toml",
        content='[tool.pytest.ini_options]\npython_files = ["check_*.py"]\n',
    )
    _write(path=tmp_path / "pinned" / "app" / "__init__.py", content="import helper\n")
    _write(
        path=tmp_path / "pinned" / "app" / "check_app.py", content="import framework\n"
    )

    groups = _detect(repo_root=tmp_path, root="pinned/app")

    assert groups.detected == {"helper"}
    assert groups.detected_test == {"framework"}
