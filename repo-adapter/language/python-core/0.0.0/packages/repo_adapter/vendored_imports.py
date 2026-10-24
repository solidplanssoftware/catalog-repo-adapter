"""Whether a Python package's tree holds every module the package imports from itself.

Asked of a vendored tree: source this repository unpacked rather than wrote. A
publish that left a module out produces an archive that registers, unpacks and
looks well-formed, while the package's own `__init__.py` imports the module it
is missing -- and the `ModuleNotFoundError` arrives in whatever process first
imports it, far from the publish that caused it. Reading the imports catches
that where the tree lands, without running anything in it.

Only imports of the package itself are checked. A third-party import is an
installer's to satisfy and a sibling package is another vendored tree's, so
neither is a statement about this tree.

Three things are deliberately not reported. An import inside a `try` whose
handler catches `ImportError` is one its author allowed to be absent. A file
that does not parse is a different failure with its own error. And a name
imported from a package with no `__init__.py` to read is only checked as a
submodule, since a namespace package defines nothing of its own.
"""

from __future__ import annotations

import ast
from collections.abc import Sequence
from pathlib import Path

from repo_adapter_api import is_non_source

#: The exceptions a guarded import is written to survive.
_IMPORT_ERRORS = frozenset({"ImportError", "ModuleNotFoundError"})

_PACKAGE_MARKER = "__init__.py"


def unresolved_package_imports(
    *, package_root: Path, package_name: str, non_source_patterns: Sequence[str]
) -> list[str]:
    """Return `<file>: <module>` for each import of the package its tree cannot satisfy.

    ``non_source_patterns`` are what the walk passes over, handed in because
    they are an adapter's to configure and no fact about Python.
    """
    name = package_name.strip()
    if not name or not package_root.is_dir():
        return []
    skipped = non_source_patterns
    found: set[str] = set()
    for source in sorted(package_root.rglob("*.py")):
        relative = source.relative_to(package_root)
        if is_non_source(relative_path=relative, patterns=skipped) or any(
            part.startswith(".") for part in relative.parts[:-1]
        ):
            continue
        try:
            tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
        except (OSError, SyntaxError, UnicodeDecodeError, ValueError):
            continue
        for module in _missing_modules(
            tree=tree, relative=relative, package_root=package_root, package_name=name
        ):
            found.add(f"{relative.as_posix()}: {module}")
    return sorted(found)


def _missing_modules(
    *, tree: ast.Module, relative: Path, package_root: Path, package_name: str
) -> list[str]:
    """The modules of the package this one file imports and the tree does not hold."""
    guarded = _guarded_nodes(tree=tree)
    # The package a file's relative imports count from: the directory holding
    # it, named from the package root. `__init__.py` is that package's own
    # file, so it counts from the same place its siblings do.
    here = [package_name, *relative.parts[:-1]]
    missing: list[str] = []
    for node in ast.walk(tree):
        if id(node) in guarded:
            continue
        if isinstance(node, ast.Import):
            for alias in node.names:
                if not _resolves(
                    package_root=package_root,
                    package_name=package_name,
                    module=alias.name,
                ):
                    missing.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            base = _absolute_module(node=node, here=here)
            if base is None or base.split(".")[0] != package_name:
                continue
            if not _resolves(
                package_root=package_root, package_name=package_name, module=base
            ):
                missing.append(base)
                continue
            directory = package_root.joinpath(*base.split(".")[1:])
            if not directory.is_dir():
                continue
            bound = _bound_names(package=directory)
            for alias in node.names:
                if alias.name == "*" or bound is None or alias.name in bound:
                    continue
                submodule = f"{base}.{alias.name}"
                if not _resolves(
                    package_root=package_root,
                    package_name=package_name,
                    module=submodule,
                ):
                    missing.append(submodule)
    return missing


def _absolute_module(*, node: ast.ImportFrom, here: list[str]) -> str | None:
    """The dotted module an `import from` names, with a relative one resolved."""
    if not node.level:
        return node.module
    trimmed = node.level - 1
    if trimmed >= len(here):
        return None
    parts = here[: len(here) - trimmed]
    if node.module:
        parts = [*parts, *node.module.split(".")]
    return ".".join(parts)


def _resolves(*, package_root: Path, package_name: str, module: str) -> bool:
    """Whether a module of this package is a file or a directory in its tree.

    A module of any other package is not this tree's to answer for, so it
    resolves by definition.
    """
    parts = module.split(".")
    if parts[0] != package_name:
        return True
    target = package_root.joinpath(*parts[1:])
    return target.is_dir() or target.with_name(f"{target.name}.py").is_file()


def _bound_names(*, package: Path) -> set[str] | None:
    """The names a package's `__init__.py` binds, or `None` when it cannot be told.

    `None` covers a star import and a module-level `__getattr__`, either of
    which can supply any name, and a file that does not parse. A package with
    no `__init__.py` binds nothing, so every name taken from it has to be a
    submodule.
    """
    marker = package / _PACKAGE_MARKER
    if not marker.is_file():
        return set()
    try:
        tree = ast.parse(marker.read_text(encoding="utf-8"), filename=str(marker))
    except (OSError, SyntaxError, UnicodeDecodeError, ValueError):
        return None
    bound: set[str] = set()
    for statement in ast.walk(tree):
        if isinstance(statement, ast.FunctionDef | ast.AsyncFunctionDef):
            if statement.name == "__getattr__":
                return None
            bound.add(statement.name)
        elif isinstance(statement, ast.ClassDef):
            bound.add(statement.name)
        elif isinstance(statement, ast.Import):
            bound.update(
                alias.asname or alias.name.split(".")[0] for alias in statement.names
            )
        elif isinstance(statement, ast.ImportFrom):
            for alias in statement.names:
                if alias.name == "*":
                    return None
                bound.add(alias.asname or alias.name)
        elif isinstance(statement, ast.Assign | ast.AnnAssign | ast.AugAssign):
            targets = (
                statement.targets
                if isinstance(statement, ast.Assign)
                else [statement.target]
            )
            for target in targets:
                bound.update(
                    node.id for node in ast.walk(target) if isinstance(node, ast.Name)
                )
    return bound


def _guarded_nodes(*, tree: ast.Module) -> set[int]:
    """Every node inside a `try` body whose handlers catch a failed import."""
    guarded: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Try | ast.TryStar):
            continue
        if not any(_catches_import_error(handler=h) for h in node.handlers):
            continue
        for statement in node.body:
            guarded.update(id(inner) for inner in ast.walk(statement))
    return guarded


def _catches_import_error(*, handler: ast.ExceptHandler) -> bool:
    """Whether a handler would catch an import that failed."""
    caught = handler.type
    if caught is None:
        return True
    names = caught.elts if isinstance(caught, ast.Tuple) else [caught]
    for name in names:
        if isinstance(name, ast.Name) and name.id in _IMPORT_ERRORS | {"Exception"}:
            return True
        if isinstance(name, ast.Attribute) and name.attr in _IMPORT_ERRORS:
            return True
    return False
