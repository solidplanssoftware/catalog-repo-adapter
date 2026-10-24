"""Where a Python application loads its definition.

An application declares itself in an ``*.app.yml`` at its module root, and one
module of its package loads that document into the object the framework runs:
``cli_config``. The declaration used to say which module, as an import path --
one language's spelling inside a document that is otherwise read the same way
by anything. So the question is answered here instead, from the source: the
module that *binds* the name is where it lives, and a module that only imports
it is a reader like any other.
"""

from __future__ import annotations

import ast
from pathlib import Path

from .tree_shape import resolve_package_name

#: The name an application's loaded definition is bound to, and the one a
#: generated API imports.
_DEFINITION_NAME = "cli_config"

#: Where a module binding it is looked for, relative to the module root and in
#: this order: the application's `src/`, which is where every application of
#: this framework keeps its code, and then the module root itself, which is
#: where one too small to have a `src/` keeps it.
_SEARCHED_DIRECTORIES = ("src", ".")


def _binds_definition(*, path: Path) -> bool:
    """Whether a module assigns the definition's name at its top level."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, UnicodeDecodeError):
        return False
    for statement in tree.body:
        if isinstance(statement, ast.Assign):
            targets = statement.targets
        elif isinstance(statement, ast.AnnAssign):
            targets = [statement.target]
        else:
            continue
        if any(
            isinstance(target, ast.Name) and target.id == _DEFINITION_NAME
            for target in targets
        ):
            return True
    return False


def resolve_app_definition_binding(*, module_root: Path, repo_root: Path) -> str | None:
    """Return the import path of the module binding an application's definition.

    The first searched directory holding exactly one such module answers. One
    holding two answers None rather than the first by name: which of them a
    generated API should import is not something a sort order knows, and a
    caller told None refuses by name where a guess would generate.
    """
    package = resolve_package_name(directory=module_root, repo_root=repo_root)
    if package is None:
        return None
    for searched in _SEARCHED_DIRECTORIES:
        directory = module_root / searched
        if not directory.is_dir():
            continue
        binding = sorted(
            path.stem for path in directory.glob("*.py") if _binds_definition(path=path)
        )
        if not binding:
            continue
        if len(binding) > 1:
            return None
        parts = [package, *([] if searched == "." else [searched]), binding[0]]
        return ".".join(parts)
    return None
