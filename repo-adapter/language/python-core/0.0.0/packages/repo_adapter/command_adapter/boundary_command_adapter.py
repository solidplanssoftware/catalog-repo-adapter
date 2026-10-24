"""Read a module's boundary files: what each imports, and what each exports."""

from __future__ import annotations

import ast
from pathlib import Path
from typing import TYPE_CHECKING

from repo_adapter_api import BoundaryExport, BoundaryFile

from .dependency_command_adapter import (
    _dependency_from_import_path,
    _resolve_relative_module_name,
)

if TYPE_CHECKING:
    from repo_adapter_api import Boundary, ManifestModule, ModuleByPackage

#: The file each boundary is, at a module's root: what a parent exposes to
#: the outside, and what a module hands the modules nested inside it.
_BOUNDARY_FILES: dict[str, str] = {
    "exports": "external_api.py",
    "facade": "submodule_api.py",
}


def read_boundary(
    *,
    module: ManifestModule,
    repo_root: Path,
    module_by_package: ModuleByPackage,
    boundary: Boundary,
) -> BoundaryFile | None:
    """Return what a module's boundary file imports and exports, or None.

    Every import counts, under `if TYPE_CHECKING:` or not, because a name the
    file re-exports only for annotations is still one read through it;
    resolved the way `dep_groups` resolves them, relative ones included, and
    the module's own name left out. Each name `__all__` lists is an export,
    with the module it is imported from where it is imported absolutely and
    not defined here, mapped to a manifest module through
    ``module_by_package``: what is made of that is the caller's to judge.
    """
    module_root = (repo_root / Path(str(module.rootDir))).resolve()
    held = module_root / _BOUNDARY_FILES[str(boundary)]
    if not held.is_file():
        return None
    repo_root_resolved = repo_root.resolve()
    try:
        parsed = ast.parse(held.read_text(encoding="utf-8"), filename=str(held))
    except (SyntaxError, UnicodeDecodeError) as exc:
        raise RuntimeError(
            f"Failed to parse the {boundary} boundary of module '{module.name}': {held}"
        ) from exc
    return BoundaryFile(
        path=held.relative_to(repo_root_resolved),
        imports=_imports(
            parsed=parsed,
            held=held,
            repo_root=repo_root_resolved,
            module_by_package=module_by_package,
            own=str(module.name),
        ),
        exports=_exports(parsed=parsed, module_by_package=module_by_package),
    )


def _imports(
    *,
    parsed: ast.Module,
    held: Path,
    repo_root: Path,
    module_by_package: ModuleByPackage,
    own: str,
) -> set[str]:
    """Every module or coordinate the file imports, the module's own left out."""
    imported: set[str] = set()
    for node in ast.walk(parsed):
        paths: list[str] = []
        if isinstance(node, ast.Import):
            paths = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            resolved = (
                _resolve_relative_module_name(
                    py_file=held,
                    repo_root=repo_root,
                    level=node.level,
                    module=node.module,
                )
                if node.level
                else node.module
            )
            if not resolved:
                continue
            # Each name at its own depth, falling back to the module it is
            # imported from, as `dep_groups` reads them.
            paths = [
                f"{resolved}.{alias.name}" for alias in node.names if alias.name != "*"
            ] + [resolved]
        for path in paths:
            name = _dependency_from_import_path(
                import_path=path, module_by_package=module_by_package
            )
            if name:
                imported.add(name)
                if isinstance(node, ast.ImportFrom):
                    break
    imported.discard(own)
    return imported


def _exports(
    *, parsed: ast.Module, module_by_package: ModuleByPackage
) -> tuple[BoundaryExport, ...]:
    """Each name `__all__` lists, with where it comes from when it comes from elsewhere."""
    defined: set[str] = set()
    imported: dict[str, tuple[str, int, int]] = {}
    listed: list[str] = []
    for node in parsed.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            defined.add(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if not isinstance(target, ast.Name):
                    continue
                if target.id == "__all__" and isinstance(
                    node.value, (ast.List, ast.Tuple)
                ):
                    listed.extend(
                        str(element.value)
                        for element in node.value.elts
                        if isinstance(element, ast.Constant)
                    )
                else:
                    defined.add(target.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            defined.add(node.target.id)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                name = alias.asname or alias.name.split(".")[0]
                imported[name] = (alias.name, node.lineno, 0)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            for alias in node.names:
                imported[alias.asname or alias.name] = (
                    node.module,
                    node.lineno,
                    node.level,
                )
    exports: list[BoundaryExport] = []
    for name in listed:
        origin = imported.get(name)
        if origin is None or name in defined:
            exports.append(BoundaryExport(name=name, source=None, line=0))
            continue
        source, line, level = origin
        exports.append(
            BoundaryExport(
                name=name,
                source=_mapped(source=source, module_by_package=module_by_package)
                if level == 0
                else None,
                line=line,
            )
        )
    return tuple(exports)


def _mapped(*, source: str, module_by_package: ModuleByPackage) -> str:
    """The manifest module a dotted import path belongs to, or the path itself."""
    parts = source.split(".")
    for length in range(len(parts), 0, -1):
        candidate = ".".join(parts[:length])
        if candidate in module_by_package:
            return module_by_package[candidate]
    return source
