"""Keep a run that names no path out of what git ignores.

A run handed no path collects what the repository's own configuration names,
and where that names nothing pytest collects from the root: every directory
under it. A repository's root also holds what it fetched rather than wrote --
the libraries it vendored, the adapter it resolved -- and those arrive with
their own tests, which are another repository's to run and cannot be imported
from here. pytest does not read `.gitignore`, so it walks into them.

Git already says which paths are not the repository's own: the ones it
ignores. With `--skip-git-ignored` this plugin asks it once, when the run is
configured, and leaves each ignored path uncollected. A path named on the
command line is somebody's selection and is never asked about, so the adapter
passes the flag only to a run it hands no path.

An untracked path git does not ignore is still collected: a test written and
not yet added is the repository's own. A root git cannot list -- no
repository, no git -- has nothing left out.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

_IGNORED = pytest.StashKey[frozenset[Path]]()


def pytest_addoption(parser: pytest.Parser) -> None:
    """Take whether the run leaves out what git ignores."""
    group = parser.getgroup("git-ignored paths")
    group.addoption(
        "--skip-git-ignored",
        action="store_true",
        default=False,
        help="Collect nothing from a path git ignores under the root.",
    )


def ignored_paths(*, root: Path) -> frozenset[Path]:
    """Return each path under ``root`` git ignores, a directory wholly ignored as itself.

    Empty where git cannot answer for ``root``.
    """
    try:
        listed = subprocess.run(
            [
                "git",
                "ls-files",
                "--others",
                "--ignored",
                "--exclude-standard",
                "--directory",
                "-z",
            ],
            cwd=root,
            capture_output=True,
            check=False,
        )
    except OSError:
        return frozenset()
    if listed.returncode != 0:
        return frozenset()
    entries = listed.stdout.decode("utf-8", errors="replace").split("\0")
    return frozenset(root / entry.rstrip("/") for entry in entries if entry)


def pytest_configure(config: pytest.Config) -> None:
    """Ask git once what it ignores, where the run was told to leave it out."""
    if config.getoption("skip_git_ignored"):
        config.stash[_IGNORED] = ignored_paths(root=config.rootpath)


def pytest_ignore_collect(collection_path: Path, config: pytest.Config) -> bool | None:
    """Leave a path git ignores uncollected, and say nothing of any other."""
    if collection_path in config.stash.get(_IGNORED, frozenset()):
        return True
    return None
