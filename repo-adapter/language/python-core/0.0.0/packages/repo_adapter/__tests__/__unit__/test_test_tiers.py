"""How a Python tree keeps a tier of tests, and how pytest is told to pass one."""

from __future__ import annotations

from pathlib import Path

import pytest
from repo_adapter_api import RepositoryConfigDocument

from repo_adapter.__tests__.python_adapter import adapter


def _config(**values: object) -> RepositoryConfigDocument:
    """The config as an adapter receives it: the serialized document."""
    return values


@pytest.mark.parametrize(
    ("name", "tier"),
    [
        ("__integration__", "integration"),
        ("__unit__", "unit"),
        # Only the spelling is read. Which names are tiers is the
        # repository's declaration, so nothing that looks like a tier is
        # listed here as not being one.
        ("__types__", "types"),
        ("__pycache__", "pycache"),
        # A package of helpers, a fixture tree.
        ("fixtures", None),
        ("_private", None),
        ("____", None),
    ],
)
def test_a_tier_s_name_is_what_a_folder_spells_between_double_underscores(
    name: str, tier: str | None
) -> None:
    assert adapter.test_tier(name=name) == tier


def test_a_run_collecting_every_tier_is_told_to_pass_nothing() -> None:
    command = adapter.test(config=_config(), paths=[Path("/repo/pkg")])

    assert command is not None
    assert command.args == ["-m", "pytest", "-n", "auto", str(Path("/repo/pkg"))]


def test_a_tier_left_out_is_passed_by_directory_wherever_a_test_package_sits() -> None:
    command = adapter.test(
        config=_config(),
        paths=[Path("/repo/pkg")],
        skipped_tiers=["integration", "system"],
    )

    assert command is not None
    assert command.args == [
        "-m",
        "pytest",
        "-n",
        "auto",
        # The test directories are a set, read in sorted order: `/tests`
        # before `__tests__`.
        "--ignore-glob=*tests/__integration__",
        "--ignore-glob=*__tests__/__integration__",
        "--ignore-glob=*tests/__system__",
        "--ignore-glob=*__tests__/__system__",
        str(Path("/repo/pkg")),
    ]


def test_nothing_but_a_tier_s_directory_is_ever_passed() -> None:
    """Every test is in a tier's directory, so there is no other rule to leave one out by."""
    command = adapter.test(config=_config(), skipped_tiers=["unit"])

    assert command is not None
    assert command.args[-2:] == [
        "--ignore-glob=*tests/__unit__",
        "--ignore-glob=*__tests__/__unit__",
    ]


def test_a_test_is_a_module_named_for_one(tmp_path: Path) -> None:
    """Everything else in a test package is support: a marker, a helper, a fixture.

    The names are pytest's own where a repository states none, with the
    file pytest loads for them.
    """
    assert list(adapter.test_file_patterns(repo_root=tmp_path)) == [
        "conftest.py",
        "*_test.py",
        "test_*.py",
    ]
