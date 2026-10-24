"""Where this adapter says a Python application loads its definition."""

from __future__ import annotations

from pathlib import Path

from repo_adapter.__tests__.python_adapter import adapter


def _application(*, repo_root: Path, modules: dict[str, str]) -> Path:
    """Write a package `app` under ``repo_root`` holding ``modules``."""
    module_root = repo_root / "app"
    for relative, source in {"__init__.py": "", **modules}.items():
        path = module_root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8")
    return module_root


def test_the_module_binding_the_definition_is_named(tmp_path: Path) -> None:
    module_root = _application(
        repo_root=tmp_path,
        modules={"src/__init__.py": "", "src/app_config.py": "cli_config = load()\n"},
    )

    assert (
        adapter.resolve_app_definition_binding(
            module_root=module_root, repo_root=tmp_path
        )
        == "app.src.app_config"
    )


def test_a_module_importing_the_definition_does_not_bind_it(tmp_path: Path) -> None:
    """`app.py` reads what `app_config.py` loaded, and so does a generated API."""
    module_root = _application(
        repo_root=tmp_path,
        modules={
            "src/__init__.py": "",
            "src/app.py": "from .definition import cli_config\nrun(cli_config)\n",
            "src/definition.py": "cli_config: object = load()\n",
            "src/app_config.py": "KEYS = ()\n",
        },
    )

    assert (
        adapter.resolve_app_definition_binding(
            module_root=module_root, repo_root=tmp_path
        )
        == "app.src.definition"
    )


def test_an_application_with_no_src_is_read_at_its_root(tmp_path: Path) -> None:
    module_root = _application(
        repo_root=tmp_path, modules={"app.py": "cli_config = load()\n"}
    )

    assert (
        adapter.resolve_app_definition_binding(
            module_root=module_root, repo_root=tmp_path
        )
        == "app.app"
    )


def test_two_modules_binding_it_are_not_chosen_between(tmp_path: Path) -> None:
    module_root = _application(
        repo_root=tmp_path,
        modules={
            "src/__init__.py": "",
            "src/a.py": "cli_config = load()\n",
            "src/b.py": "cli_config = load()\n",
        },
    )

    assert (
        adapter.resolve_app_definition_binding(
            module_root=module_root, repo_root=tmp_path
        )
        is None
    )


def test_nothing_binding_it_answers_none(tmp_path: Path) -> None:
    module_root = _application(
        repo_root=tmp_path, modules={"src/__init__.py": "", "src/app.py": "x = 1\n"}
    )

    assert (
        adapter.resolve_app_definition_binding(
            module_root=module_root, repo_root=tmp_path
        )
        is None
    )


def test_a_directory_that_is_no_package_answers_none(tmp_path: Path) -> None:
    module_root = tmp_path / "app"
    module_root.mkdir()
    (module_root / "app.py").write_text("cli_config = load()\n", encoding="utf-8")

    assert (
        adapter.resolve_app_definition_binding(
            module_root=module_root, repo_root=tmp_path
        )
        is None
    )
