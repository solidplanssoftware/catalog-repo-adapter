from __future__ import annotations

import ast
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING

from repo_adapter_api import (
    DependencyGroups,
    is_non_source,
    is_test_file,
)

if TYPE_CHECKING:
    from repo_adapter_api import ManifestModule, ModuleByPackage

# The manifest fields the scan reads -- `rootDir`, `name` and, where the
# module states one, `entryPoint` -- as a mapping rather than the
# model: `dep_groups` is called both with a `ManifestModule` reduced to
# these fields and with a literal in tests. It is this package's own
# shape, not part of the adapter contract -- the contract package
# exports no such name, and importing one from it type-checked only
# because nothing was checking this tree.
ModuleConfig = Mapping[str, str]


def _is_skipped(*, py_file: Path, non_source_patterns: Sequence[str]) -> bool:
    """Return whether the file sits under an environment, a fetched or a built tree.

    The patterns are handed in rather than read here, and `tree_shape` is where
    this package keeps them. Reaching for them from this module would be a
    module importing another module's internals -- `..tree_shape` or
    `repo_adapter.tree_shape`, and the second is what ROI001 refuses -- so the
    facade, which already holds both, passes them down. They are read by the
    contract's own `is_non_source`.

    This scan used to hold a second list of its own -- `build`, `dist`, `lib`
    and `node_modules`, matched at any depth -- which disagreed with
    `tree_shape`'s in both directions and, by matching `build` loosely, kept
    dev-tool's whole `registry/app/build/` command package out of every
    dependency scan ever run. `lib` is the entry with the subtlest cost when it
    is wrong the other way: it is another repository's source, unpacked by a
    vendoring step, and scanning it reports the *dependency's* internal
    structure as this module's imports.

    A dot-prefixed part is skipped here as everywhere: this framework keeps
    configuration and tooling state under one, never source.
    """
    return is_non_source(relative_path=py_file, patterns=non_source_patterns) or any(
        part.startswith(".") for part in py_file.parts
    )


def _is_type_checking_test(*, test: ast.expr) -> bool:
    """Return whether an `if` guard is the TYPE_CHECKING idiom."""
    if isinstance(test, ast.Name):
        return test.id == "TYPE_CHECKING"
    if isinstance(test, ast.Attribute):
        return test.attr == "TYPE_CHECKING"
    return False


def _declared_files(*, module: ModuleConfig, module_root: Path) -> set[Path]:
    """The files a manifest names as the module itself.

    A module rooted at one file, and the file a module names as its entry
    point. What a manifest declares as a module's own code is that module's
    code whatever the file is called: this tree's test libraries each enter
    through a `test_support.py`, which is a library other packages' tests
    import and not a test -- its imports are what a consumer of the library
    needs at run time. A name's shape is a convention, and a declaration is
    read before one.
    """
    if module_root.is_file():
        return {module_root}
    entry_point = str(module.get("entryPoint") or "").strip()
    if not entry_point:
        return set()
    return {(module_root / entry_point).resolve()}


def _module_name_from_file(*, py_file: Path, repo_root: Path) -> list[str]:
    """Derive the Python module name from the given file path."""
    module_path = py_file.relative_to(repo_root).with_suffix("")
    module_parts = list(module_path.parts)
    if not module_parts:
        return []
    return module_parts[:-1]


def _resolve_relative_module_name(
    *,
    py_file: Path,
    repo_root: Path,
    level: int,
    module: str | None,
) -> str | None:
    """Resolve a module name relative to the current package context."""
    package_parts = _module_name_from_file(py_file=py_file, repo_root=repo_root)
    parents_to_trim = level - 1
    if parents_to_trim < 0 or parents_to_trim > len(package_parts):
        return None

    target_parts = package_parts[: len(package_parts) - parents_to_trim]
    if module:
        target_parts.extend(part for part in module.split(".") if part)

    if not target_parts:
        return None
    return ".".join(target_parts)


def _dependency_from_import_path(
    *,
    import_path: str,
    module_by_package: ModuleByPackage,
) -> str | None:
    """Create a dependency entry from the provided import path."""
    parts = [part.strip() for part in import_path.split(".") if part.strip()]
    for length in range(len(parts), 0, -1):
        candidate = ".".join(parts[:length])
        dependency_name = module_by_package.get(candidate)
        if dependency_name:
            return dependency_name
    return None


def _owning_module(
    *,
    py_file: Path,
    repo_root: Path,
    module_by_package: ModuleByPackage,
) -> str | None:
    """The module a file's imports belong to.

    The longest declared package prefix of the file's dotted path wins,
    which is what keeps a module whose root directory encloses other
    modules -- a parent over its submodules -- from being credited with
    their imports: each file is scanned by exactly the module that owns
    it, never by every ancestor whose tree it happens to sit in.
    """
    dotted = ".".join(py_file.relative_to(repo_root).with_suffix("").parts)
    return _dependency_from_import_path(
        import_path=dotted, module_by_package=module_by_package
    )


def dep_groups(
    *,
    module: ModuleConfig,
    repo_root: Path,
    module_by_package: ModuleByPackage,
    non_source_patterns: Sequence[str],
    test_patterns: Sequence[str],
) -> DependencyGroups:
    """Return dependency groups detected from the module's Python imports.

    ``non_source_patterns`` is what this language says holds none of a
    module's own source, and ``test_patterns`` what it says is a test file in
    this repository, rooted at ``repo_root``; both are handed in by the caller
    that has them, and are the answers the adapter gives every other caller.
    An import made from a test file is a test dependency and nothing else.
    """

    root_dir = Path(str(module["rootDir"]))
    module_root = (repo_root / root_dir).resolve()
    module_name = str(module["name"])

    detected_dependencies: set[str] = set()
    detected_dev_dependencies: set[str] = set()
    detected_test_dependencies: set[str] = set()
    repo_root_resolved = repo_root.resolve()
    # A module root is usually a directory to walk, and may be a single file
    # that is the whole module -- a declared unit small enough to live in one
    # file. Walking it yields nothing, so the file itself is the scan.
    if module_root.is_file():
        module_files = [module_root]
        scan_root = module_root.parent
    else:
        module_files = sorted(module_root.rglob("*.py"))
        scan_root = module_root
    declared_files = _declared_files(module=module, module_root=module_root)
    for py_file in module_files:
        if _is_skipped(
            py_file=py_file.relative_to(scan_root),
            non_source_patterns=non_source_patterns,
        ):
            continue
        owner = _owning_module(
            py_file=py_file.resolve(),
            repo_root=repo_root_resolved,
            module_by_package=module_by_package,
        )
        if owner is not None and owner != module_name:
            continue
        is_test = py_file.resolve() not in declared_files and is_test_file(
            relative_path=py_file.resolve().relative_to(repo_root_resolved),
            patterns=test_patterns,
        )

        try:
            source = py_file.read_text(encoding="utf-8")
            parsed = ast.parse(source, filename=str(py_file))
        except (SyntaxError, UnicodeDecodeError) as exc:
            raise RuntimeError(
                f"Failed to parse Python source for module '{module_name}': {py_file}"
            ) from exc

        def visit(node: ast.AST, *, type_only: bool) -> None:
            """Collect this node's imports, tracking TYPE_CHECKING guards.

            An import under `if TYPE_CHECKING:` never runs, so it is a
            development-time dependency -- the classification the
            declared graph's devDependencies exist for. A hand-rolled
            walk rather than ast.walk because the guard is contextual:
            the flag has to travel down the guarded branch and only
            that branch.
            """
            if isinstance(node, ast.If) and _is_type_checking_test(test=node.test):
                for child in node.body:
                    visit(child, type_only=True)
                for child in node.orelse:
                    visit(child, type_only=type_only)
                return
            if is_test:
                target_dependencies = detected_test_dependencies
            elif type_only:
                target_dependencies = detected_dev_dependencies
            else:
                target_dependencies = detected_dependencies
            if isinstance(node, ast.Import):
                for alias in node.names:
                    dependency_name = _dependency_from_import_path(
                        import_path=alias.name,
                        module_by_package=module_by_package,
                    )
                    if dependency_name and dependency_name != module_name:
                        target_dependencies.add(dependency_name)
            elif isinstance(node, ast.ImportFrom):
                if node.level and node.level > 0:
                    resolved_module = _resolve_relative_module_name(
                        py_file=py_file.resolve(),
                        repo_root=repo_root_resolved,
                        level=node.level,
                        module=node.module,
                    )
                else:
                    resolved_module = node.module
                if not resolved_module:
                    return

                # Each alias resolved at its own depth, and every one of
                # them: `from .. import git, session` names two modules,
                # and resolving the bare package first credited whichever
                # module happened to own the package directory while the
                # named modules went unseen.
                matched = False
                for alias in node.names:
                    if alias.name == "*":
                        continue
                    dependency_name = _dependency_from_import_path(
                        import_path=f"{resolved_module}.{alias.name}",
                        module_by_package=module_by_package,
                    )
                    if dependency_name:
                        matched = True
                        if dependency_name != module_name:
                            target_dependencies.add(dependency_name)
                if not matched:
                    dependency_name = _dependency_from_import_path(
                        import_path=resolved_module,
                        module_by_package=module_by_package,
                    )
                    if dependency_name and dependency_name != module_name:
                        target_dependencies.add(dependency_name)
            for child in ast.iter_child_nodes(node):
                visit(child, type_only=type_only)

        visit(parsed, type_only=False)

    return DependencyGroups(
        detected=detected_dependencies,
        detected_test=detected_test_dependencies,
        detected_dev=detected_dev_dependencies,
    )


def discover_dependency_groups(
    *,
    module: ManifestModule,
    repo_root: Path,
    module_by_package: ModuleByPackage,
    non_source_patterns: Sequence[str],
    test_patterns: Sequence[str],
) -> DependencyGroups:
    """Return dependency groups detected from the module's Python imports."""
    module_config = {
        "rootDir": module.rootDir,
        "name": module.name,
        "entryPoint": str(module.entryPoint or ""),
    }
    return dep_groups(
        module=module_config,
        repo_root=repo_root,
        module_by_package=module_by_package,
        non_source_patterns=non_source_patterns,
        test_patterns=test_patterns,
    )
