"""Hold an isolated tier's tests to starting no process.

A repository declares which tiers of its tests are isolated -- the unit tier,
which crosses no process boundary and is what runs after every edit. This is
what holds a test to that: while a test in an isolated tier runs, starting a
process is refused, and the test fails saying what it tried to start and
where it belongs instead.

It is a pytest plugin, loaded by the command the adapter builds for a test
run, and it knows a test's tier the way everything else does: by the
directory the test sits in inside `__tests__`.

A refusal is raised where the process would have started, and reported again
when the test ends. Raised, because the code under test must not go on as
though the process had run. Reported again, because code that catches what
it cannot handle would otherwise turn the refusal into some unrelated
failure, or into none.

What is refused is `subprocess.Popen`, which `subprocess.run`, `check_call`,
`check_output` and `os.popen` all go through, and `os.system`. A test that
replaces `subprocess.run` with a stand-in never reaches either, which is the
point: a unit test stands the process boundary in, and an integration test
crosses it.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest

#: The directory a Python tree keeps its tests in. Stated here as well as in
#: the adapter because this file is loaded into the suite's process, where
#: the adapter is not.
_TEST_DIRECTORY = "__tests__"


def pytest_addoption(parser: pytest.Parser) -> None:
    """Take the tiers the repository declares isolated."""
    group = parser.getgroup("tier isolation")
    group.addoption(
        "--isolated-tier",
        action="append",
        default=[],
        help="A tier whose tests may start no process; repeat for several.",
    )


def tier_of(*, path: Path) -> str | None:
    """Return the name a test file's directory spells as a tier's, or None.

    None for a file outside a test directory, and `''` for one in it that
    sits under no directory spelled as a tier's. Only the spelling is read:
    which names are tiers is what the run was told with `--isolated-tier`.
    """
    parts = path.parts[:-1]
    if _TEST_DIRECTORY not in parts:
        return None
    below = parts[parts.index(_TEST_DIRECTORY) + 1 :]
    if not below:
        return ""
    name = below[0]
    if len(name) > 4 and name.startswith("__") and name.endswith("__"):
        return name[2:-2]
    return ""


def _isolated(*, request: pytest.FixtureRequest) -> bool:
    """Whether the test being run is in a tier that may start no process."""
    tier = tier_of(path=Path(str(request.node.path)))
    if not tier:
        return False
    return tier in list(request.config.getoption("isolated_tier") or [])


class ProcessStartedInIsolatedTier(AssertionError):
    """A test in an isolated tier tried to start a process."""


@pytest.fixture(autouse=True)
def _starts_no_process(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> Iterator[None]:
    """Refuse a process started by a test in an isolated tier, and say so at its end."""
    if not _isolated(request=request):
        yield
        return
    started: list[str] = []

    def _refused(*, what: object) -> ProcessStartedInIsolatedTier:
        """Record one attempt, and return the refusal to raise for it."""
        started.append(repr(what))
        return ProcessStartedInIsolatedTier(
            f"this test is in a tier that starts no process, and it started "
            f"{what!r}. Stand the process in, or move the test to "
            f"{_TEST_DIRECTORY}/__integration__/, which CI runs."
        )

    def _popen(
        self: object, args: object = None, *rest: object, **named: object
    ) -> None:
        """Stand in for `subprocess.Popen.__init__`."""
        del self, rest
        raise _refused(what=named.get("args", args))

    def _system(command: object) -> int:
        """Stand in for `os.system`."""
        raise _refused(what=command)

    monkeypatch.setattr(subprocess.Popen, "__init__", _popen)
    monkeypatch.setattr(os, "system", _system)
    yield
    if started:
        pytest.fail(
            "this test is in a tier that starts no process, and it started "
            + "; ".join(started)
            + f". Stand the process in, or move the test to "
            f"{_TEST_DIRECTORY}/__integration__/, which CI runs.",
            pytrace=False,
        )
