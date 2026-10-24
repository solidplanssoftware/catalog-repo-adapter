"""An isolated tier is held to starting no process, by a real run of the command.

The plugin does its work inside pytest, so what is asserted here is a pytest
run: a small tree of tests is written under a temporary root, the command the
adapter builds is started against it, and what the run reports is read back.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from repo_adapter_api import RepositoryConfigDocument

from repo_adapter.__tests__.python_adapter import adapter

_STARTS = (
    "import subprocess, sys\n\n\n"
    "def test_starts_a_process():\n"
    '    subprocess.run([sys.executable, "-c", "pass"], check=True)\n'
)
_STANDS_IN = (
    "import subprocess\n\n\n"
    "def test_stands_the_process_in(monkeypatch):\n"
    '    monkeypatch.setattr(subprocess, "run", lambda *a, **k: 0)\n'
    '    assert subprocess.run(["git"]) == 0\n'
)
_SWALLOWS = (
    "import subprocess, sys\n\n\n"
    "def test_swallows_the_refusal():\n"
    "    try:\n"
    '        subprocess.run([sys.executable, "-c", "pass"])\n'
    "    except Exception:\n"
    "        pass\n"
)


def _config(**values: object) -> RepositoryConfigDocument:
    """The config as an adapter receives it: the serialized document."""
    return values


def _tree(*, root: Path) -> None:
    """A package whose tests are kept in both tiers."""
    tests = root / "pkg" / "__tests__"
    for directory in (tests, tests / "__unit__", tests / "__integration__"):
        directory.mkdir(parents=True)
        (directory / "__init__.py").write_text("", encoding="utf-8")
    (root / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (tests / "__unit__" / "test_starts.py").write_text(_STARTS, encoding="utf-8")
    (tests / "__unit__" / "test_stands_in.py").write_text(_STANDS_IN, encoding="utf-8")
    (tests / "__unit__" / "test_swallows.py").write_text(_SWALLOWS, encoding="utf-8")
    (tests / "__integration__" / "test_starts.py").write_text(_STARTS, encoding="utf-8")


def _run(*, root: Path, **tiers: object) -> str:
    """Run the adapter's test command over the tree, and return what it printed."""
    command = adapter.test(config=_config(), paths=[root], **tiers)  # type: ignore[arg-type]
    assert command is not None
    # One process, and no cache written into the tree: what is being read is
    # each test's own outcome. Uncoloured, because an outcome is read off the
    # start of its line, and a shell that sets `FORCE_COLOR` -- an agent's
    # does -- has pytest put an escape sequence there.
    arguments = [arg for arg in command.args if arg not in ("-n", "auto")]
    done = subprocess.run(
        [
            command.executable,
            *arguments,
            "-rA",
            "-p",
            "no:cacheprovider",
            "--color=no",
        ],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    return done.stdout + done.stderr


def _outcomes(*, printed: str) -> dict[str, str]:
    """Each test's outcome, by the path it sits at below the test directory."""
    outcomes: dict[str, str] = {}
    for line in printed.splitlines():
        verdict, _, rest = line.partition(" ")
        if verdict in ("PASSED", "FAILED", "ERROR") and "__tests__" in rest:
            name = rest.split(" ")[0].replace("\\", "/").split("__tests__/")[1]
            # A refusal reported at a test's end is an error beside its own
            # outcome; the worse of the two is what the test came to.
            if outcomes.get(name) != "FAILED":
                outcomes[name] = verdict
    return outcomes


def test_a_test_in_an_isolated_tier_that_starts_a_process_fails_naming_it(
    tmp_path: Path,
) -> None:
    _tree(root=tmp_path)

    printed = _run(root=tmp_path, isolated_tiers=["unit"])

    assert _outcomes(printed=printed) == {
        "__unit__/test_starts.py::test_starts_a_process": "FAILED",
        # Standing the process in never reaches the boundary.
        "__unit__/test_stands_in.py::test_stands_the_process_in": "PASSED",
        # Code that catches what it cannot handle does not hide the attempt:
        # it is reported again when the test ends.
        "__unit__/test_swallows.py::test_swallows_the_refusal": "ERROR",
        # A tier that is not isolated crosses the boundary as it is for.
        "__integration__/test_starts.py::test_starts_a_process": "PASSED",
    }
    # What it started is named as the test wrote it, a path quoted as Python
    # quotes one.
    assert "and it started" in printed
    assert Path(sys.executable).name in printed
    assert "__tests__/__integration__/" in printed


def test_only_the_tiers_the_run_names_are_held(tmp_path: Path) -> None:
    """Which tiers are isolated is the repository's declaration, handed to the run."""
    _tree(root=tmp_path)

    outcomes = _outcomes(printed=_run(root=tmp_path, isolated_tiers=["integration"]))

    assert outcomes["__unit__/test_starts.py::test_starts_a_process"] == "PASSED"
    assert outcomes["__integration__/test_starts.py::test_starts_a_process"] == "FAILED"


def test_a_run_holding_no_tier_starts_what_its_tests_start(tmp_path: Path) -> None:
    _tree(root=tmp_path)

    outcomes = _outcomes(printed=_run(root=tmp_path))

    assert outcomes["__unit__/test_starts.py::test_starts_a_process"] == "PASSED"
    assert outcomes["__integration__/test_starts.py::test_starts_a_process"] == "PASSED"
