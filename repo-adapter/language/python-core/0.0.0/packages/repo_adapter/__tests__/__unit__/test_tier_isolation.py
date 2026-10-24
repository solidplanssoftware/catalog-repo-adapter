"""How a test run is told to hold an isolated tier, and which tier a test is in."""

from __future__ import annotations

from pathlib import Path

import pytest
from repo_adapter_api import RepositoryConfigDocument

from repo_adapter.__tests__.python_adapter import adapter
from repo_adapter.pytest_plugins.tier_isolation import tier_of


def _config(**values: object) -> RepositoryConfigDocument:
    """The config as an adapter receives it: the serialized document."""
    return values


@pytest.mark.parametrize(
    ("path", "tier"),
    [
        ("pkg/__tests__/test_a.py", ""),
        ("pkg/__tests__/__unit__/test_a.py", "unit"),
        ("pkg/__tests__/__integration__/deep/test_a.py", "integration"),
        # A helper package inside the test directory spells no tier.
        ("pkg/__tests__/fixtures/test_a.py", ""),
        # Only the spelling is read: the run says which names it holds.
        ("pkg/__tests__/__types__/test_a.py", "types"),
        # And a file outside any test directory is no test's.
        ("pkg/src/test_a.py", None),
    ],
)
def test_a_test_s_tier_is_spelled_by_where_it_sits(path: str, tier: str | None) -> None:
    assert tier_of(path=Path(path)) == tier


def test_a_run_holding_no_tier_is_plain_pytest() -> None:
    command = adapter.test(config=_config(), paths=[Path("/repo/pkg")])

    assert command is not None
    assert command.args[:2] == ["-m", "pytest"]
    assert "-p" not in command.args


def test_a_run_holding_a_tier_loads_the_plugin_from_beside_the_adapter() -> None:
    """The adapter is never installed, so the plugin's directory is put on the path."""
    command = adapter.test(
        config=_config(),
        paths=[Path("/repo/pkg")],
        isolated_tiers=["unit"],
    )

    assert command is not None
    flag, bootstrap, plugin_directory, *rest = command.args
    assert flag == "-c"
    assert "pytest.main(sys.argv[1:])" in bootstrap
    assert Path(plugin_directory).name == "pytest_plugins"
    assert (Path(plugin_directory) / "tier_isolation.py").is_file()
    assert rest == [
        "-p",
        "tier_isolation",
        "--isolated-tier",
        "unit",
        "-n",
        "auto",
        str(Path("/repo/pkg")),
    ]
