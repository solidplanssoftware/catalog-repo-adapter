"""A run handed no path collects nothing git ignores, by a real run of the command.

The plugin does its work inside pytest, so what is asserted here is a pytest
run over a small repository under a temporary root: one test of its own, one
written and not yet added, and one inside a directory git ignores, which
cannot be imported from there.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from repo_adapter_api import RepositoryConfigDocument

from repo_adapter.__tests__.python_adapter import adapter

_PASSES = "def test_passes():\n    pass\n"
#: A fetched tree's test: it imports a package that is not on the path here.
_FOREIGN = "import a_package_nobody_installed\n\n\ndef test_foreign():\n    pass\n"


def _config(**values: object) -> RepositoryConfigDocument:
    """The config as an adapter receives it: the serialized document."""
    return values


def _git(*arguments: str, cwd: Path) -> None:
    subprocess.run(["git", *arguments], cwd=cwd, check=True, capture_output=True)


def _repository(*, root: Path, ignore: str) -> None:
    """A repository whose root holds its own tests and a tree it fetched."""
    # The runner's own root, so it reads no configuration above this one, and
    # one naming nowhere to start, so the run collects from the root.
    (root / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    (root / ".gitignore").write_text(ignore, encoding="utf-8")
    for name, body in (
        ("own/test_tracked.py", _PASSES),
        ("fetched/tests/test_foreign.py", _FOREIGN),
    ):
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(body, encoding="utf-8")
    _git("init", "-q", cwd=root)
    _git("add", "-A", cwd=root)
    # Written after the add: untracked, and ignored by nothing.
    (root / "own" / "test_untracked.py").write_text(_PASSES, encoding="utf-8")


def _run(*, root: Path, paths: list[Path]) -> subprocess.CompletedProcess[str]:
    """Run the adapter's test command at the root, in one process."""
    command = adapter.test(config=_config(), paths=paths)
    assert command is not None
    arguments = [arg for arg in command.args if arg not in ("-n", "auto")]
    return subprocess.run(
        [command.executable, *arguments, "-rA", "-p", "no:cacheprovider"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )


def test_a_run_handed_no_path_leaves_out_what_git_ignores(tmp_path: Path) -> None:
    _repository(root=tmp_path, ignore="/fetched/\n")

    done = _run(root=tmp_path, paths=[])

    assert done.returncode == 0, done.stdout + done.stderr
    assert "test_foreign" not in done.stdout
    # Its own tests ran, the one git does not track yet among them.
    assert "2 passed" in done.stdout


def test_a_tree_git_does_not_ignore_is_collected(tmp_path: Path) -> None:
    """Only git's answer leaves a path out: nothing is known by its name."""
    _repository(root=tmp_path, ignore="")

    done = _run(root=tmp_path, paths=[])

    assert done.returncode != 0
    assert "test_foreign" in done.stdout


def test_a_path_named_outright_is_collected_whatever_git_says(tmp_path: Path) -> None:
    _repository(root=tmp_path, ignore="/fetched/\n")

    done = _run(root=tmp_path, paths=[tmp_path / "fetched"])

    assert done.returncode != 0
    assert "test_foreign" in done.stdout
