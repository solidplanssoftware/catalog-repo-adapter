from __future__ import annotations

from pathlib import Path

from repo_adapter_api import RepositoryConfigDocument

from repo_adapter.__tests__.python_adapter import adapter


def _config(**values: object) -> RepositoryConfigDocument:
    """The config as an adapter receives it: the serialized document."""
    return values


def test_test_command_appends_selected_paths_to_pytest_argv() -> None:

    command = adapter.test(
        config=_config(),
        paths=[Path("/repo/pkg/__tests__/test_timing.py")],
    )

    assert command is not None
    assert command.args == [
        "-m",
        "pytest",
        "-n",
        "auto",
        str(Path("/repo/pkg/__tests__/test_timing.py")),
    ]


def test_test_command_distributes_a_narrowed_run_too() -> None:
    """One rule for every run, because `paths` does not mean "a selection".

    A repository that pins others is run over its own source, and those
    paths are its whole suite. Nothing in the call says which of the two a
    path list is, so the floor is paid on both.
    """

    command = adapter.test(
        config=_config(),
        paths=[Path("/repo/pkg/__tests__/test_timing.py")],
    )

    assert command is not None
    assert command.args[:4] == ["-m", "pytest", "-n", "auto"]


def test_test_command_without_paths_runs_the_whole_suite() -> None:
    """No path is handed on, and the run is kept out of what git ignores."""

    command = adapter.test(config=_config())

    assert command is not None
    flag, _bootstrap, plugin_directory, *rest = command.args
    assert flag == "-c"
    assert (Path(plugin_directory) / "git_ignored.py").is_file()
    assert rest == ["-p", "git_ignored", "--skip-git-ignored", "-n", "auto"]


def test_test_command_naming_paths_asks_git_nothing() -> None:
    """A path named outright is collected whatever git says of it."""

    command = adapter.test(config=_config(), paths=[Path("/repo/pkg")])

    assert command is not None
    assert "--skip-git-ignored" not in command.args


def test_test_command_leaves_the_repository_s_addopts_alone() -> None:
    """`addopts` says how a repository's suite is collected.

    Overriding it dropped `--pyargs` from every repository naming its tests by
    package, and pytest collected from the root instead, vendored `lib/` and all.
    """

    for command in (
        adapter.test(config=_config()),
        adapter.test(config=_config(), paths=[Path("/repo/pkg")]),
    ):
        assert command is not None
        assert not any(arg.startswith("--override-ini") for arg in command.args)


def test_test_command_distribution_does_not_depend_on_the_ci_flag() -> None:
    """`-n auto` already reads the running machine's core count."""

    unnarrowed_ci = adapter.test(config=_config(), ci=True)
    unnarrowed = adapter.test(config=_config())
    narrowed_ci = adapter.test(config=_config(), paths=[Path("/repo/pkg")], ci=True)
    narrowed = adapter.test(config=_config(), paths=[Path("/repo/pkg")])

    assert unnarrowed_ci is not None
    assert unnarrowed is not None
    assert narrowed_ci is not None
    assert narrowed is not None
    assert unnarrowed_ci.args == unnarrowed.args
    assert narrowed_ci.args == narrowed.args


def test_format_command_narrows_to_selected_paths() -> None:

    command = adapter.format(
        config=_config(),
        paths=[Path("/repo/src"), Path("/repo/lint")],
    )

    assert command is not None
    assert command.args == [
        "run",
        "python",
        "-m",
        "ruff",
        "format",
        "/repo/src",
        "/repo/lint",
    ]


def test_format_command_without_paths_formats_the_default_surface() -> None:

    command = adapter.format(config=_config())

    assert command is not None
    assert command.args == ["run", "python", "-m", "ruff", "format"]


def test_lint_command_narrows_to_selected_paths() -> None:
    """Linting Python is ruff, and ruff takes the paths a run selected."""

    command = adapter.lint(
        config=_config(),
        paths=[Path("/repo/src")],
        exclude=["/src/__types__"],
    )

    assert command is not None
    assert command.args == [
        "run",
        "python",
        "-m",
        "ruff",
        "check",
        "--extend-exclude",
        "./src/__types__",
        "/repo/src",
    ]


def test_lint_command_without_paths_covers_the_default_surface() -> None:

    command = adapter.lint(
        config=_config(),
        fix=True,
        exclude=["__types__", "fixtures/data"],
    )

    assert command is not None
    # Each glob as ruff reads a pattern: a lone name as written, an unrooted
    # one of several segments as itself and as what lies beneath it.
    assert command.args == [
        "run",
        "python",
        "-m",
        "ruff",
        "check",
        "--fix",
        "--extend-exclude",
        "__types__",
        "--extend-exclude",
        "**/fixtures/data",
        "--extend-exclude",
        "**/fixtures/data/**",
    ]


def test_typecheck_command_narrows_to_selected_paths() -> None:

    command = adapter.typecheck(
        config=_config(),
        paths=[Path("/repo/src"), Path("/repo/lint")],
    )

    assert command is not None
    assert command.args == [
        "run",
        "python",
        "-m",
        "pyright",
        "/repo/src",
        "/repo/lint",
    ]


def test_typecheck_command_without_paths_scans_the_default_surface() -> None:

    command = adapter.typecheck(config=_config())

    assert command is not None
    assert command.args == ["run", "python", "-m", "pyright"]
