"""The Python language core: what is true of any Python repository.

One half of an adapter, and the half that is code. How an import names a
module, where a package declares what it exports, how `pyproject.toml` spells
a requirement or a package root, how pytest is told to leave a tier out: each
is a fact about Python and its tools, the same in every Python repository,
and is written here once. What two Python repositories may differ on -- where
they keep tests, what their checkouts ignore, which linter and formatter they
run -- is no part of this package. It is an adapter's configuration document,
which names this core by coordinate, and `repo_adapter_api.configure_adapter`
makes the adapter out of the two. So a second Python adapter is a second
document, and carries no copy of anything here.
"""

from __future__ import annotations

import sys
import tomllib
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

from process import Command
from repo_adapter_api import (
    Boundary,
    BoundaryFile,
    DependencyGroups,
    PackagedFile,
    PackagingInputs,
    PathSource,
    VendoredRequirementsFile,
    all_non_source_patterns,
    test_patterns_of,
)

from .app_definition import (
    resolve_app_definition_binding as resolve_app_definition_binding_adapter,
)
from .command_adapter.boundary_command_adapter import (
    read_boundary as read_boundary_adapter,
)
from .command_adapter.build_command_adapter import build as build_adapter
from .command_adapter.comments_command_adapter import (
    extract_comments as extract_comments_adapter,
)
from .command_adapter.dependency_command_adapter import (
    discover_dependency_groups as discover_dependency_groups_adapter,
)
from .tree_shape import (
    declared_language_requirements as declared_language_requirements_adapter,
)
from .tree_shape import (
    declared_package_data as declared_package_data_adapter,
)
from .tree_shape import (
    declared_path_sources as declared_path_sources_adapter,
)
from .tree_shape import (
    git_ignored_arguments,
    pytest_with_plugins,
    skipped_tier_arguments,
    tier_isolation_arguments,
)
from .tree_shape import (
    language_version as language_version_adapter,
)
from .tree_shape import (
    pytest_root as pytest_root_adapter,
)
from .tree_shape import (
    render_vendored_requirements as render_vendored_requirements_adapter,
)
from .tree_shape import (
    resolve_package_name as resolve_package_name_adapter,
)
from .tree_shape import (
    test_file_patterns as test_file_patterns_adapter,
)
from .vendored_imports import (
    unresolved_package_imports as unresolved_package_imports_adapter,
)

if TYPE_CHECKING:
    from repo_adapter_api import (
        AdapterConfiguration,
        ManifestModule,
        ModuleByPackage,
        RepositoryConfigDocument,
    )
    from schema import GeneratedTypeArtifact, SchemaDocument


def _spellings(*, globs: Iterable[object]) -> tuple[str, ...]:
    """Each glob of an adapter's configuration as it is written.

    The configuration holds globs, checked where it loaded; what this core
    hands on, inward and across the contract, is their spelling, which every
    reader matches as `type.Glob` reads it.
    """
    return tuple(str(glob) for glob in globs)


class PythonCore:
    """The Python language core every Python adapter configures."""

    # The contract this core was written to, stated rather than read off the
    # contract that happens to load it: read off, the two could never differ
    # and the loader's check would refuse nothing. A release of the contract
    # writes the number here as it writes its own.
    apiVersion = "0.0.0"
    language = "python"
    # The Python versions this core has been run against, and a statement
    # of nothing wider. A list is the span from its lowest item to its
    # highest, and a version is added here by running on it.
    #
    # The core itself runs under the tool's interpreter, 3.13 on CI and
    # 3.14 in a session, whatever a repository is written for; what a
    # version here says is that a repository written for it has been read.
    # 3.13 is every repository of the tree this is developed in. 3.9 and
    # 3.10 are two repositories written for other frameworks (the owner's
    # ruling of 2026-10-11, on the first one refused for being below
    # 3.13): one declaring `>=3.9`, vendored for, read by both dependency
    # validators, and its suite run through `test` under 3.9, 3.10, 3.11
    # and 3.12 interpreters; one declaring `>=3.10`, taken through the
    # whole gate and its suite. Nothing here reads a repository's source
    # by its version: it is parsed by the tool's interpreter, which reads
    # every syntax those versions have.
    languageVersions = ["3.9", "3.14"]

    def language_version(self, *, repo_root: Path) -> str | None:
        """Return the lowest Python version the repository says it runs on."""
        return language_version_adapter(repo_root=repo_root)

    def discover_dependency_groups(
        self,
        *,
        module: ManifestModule,
        repo_root: Path,
        module_by_package: ModuleByPackage,
        configuration: AdapterConfiguration,
    ) -> DependencyGroups:
        """Return dependency groups detected from the module's Python imports."""

        return discover_dependency_groups_adapter(
            module=module,
            repo_root=repo_root,
            module_by_package=module_by_package,
            # What the scan skips and what it files as a test are the
            # adapter's to configure, so they are handed down rather than
            # held here. The test patterns are the same answer every caller
            # across the contract gets.
            non_source_patterns=all_non_source_patterns(
                patterns=_spellings(globs=configuration.nonSourcePatterns)
            ),
            # Read from the pytest configuration nearest the module, which is
            # the one its tests run by: a tree detected from its root pins
            # repositories that each state their own.
            test_patterns=test_patterns_of(
                directories=_spellings(globs=configuration.testDirectories),
                file_patterns=test_file_patterns_adapter(
                    repo_root=pytest_root_adapter(
                        directory=repo_root / str(module.rootDir),
                        repo_root=repo_root,
                    ),
                    default_patterns=_spellings(globs=configuration.testFilePatterns),
                ),
            ),
        )

    def read_boundary(
        self,
        *,
        module: ManifestModule,
        repo_root: Path,
        module_by_package: ModuleByPackage,
        boundary: Boundary,
    ) -> BoundaryFile | None:
        """Return what `external_api.py` or `submodule_api.py` imports and exports."""
        return read_boundary_adapter(
            module=module,
            repo_root=repo_root,
            module_by_package=module_by_package,
            boundary=boundary,
        )

    def build(
        self,
        *,
        entrypoint: Path,
        target_name: str,
        artifact_name: str,
        dist_path: Path,
        scratch_path: Path,
        packaging: PackagingInputs,
        config: RepositoryConfigDocument,
        configuration: AdapterConfiguration,
    ) -> Command | None:
        """Build an executable command for packaging the target entrypoint."""

        # The module's name reaches the compiler through nothing here: the
        # artifact's filename is resolved for it, and so is the directory its
        # intermediates go in, which is where the name used to be spent.
        del config, target_name
        return build_adapter(
            entrypoint=entrypoint,
            artifact_name=artifact_name,
            dist_path=dist_path,
            scratch_path=scratch_path,
            packaging=packaging,
            test_directories=_spellings(globs=configuration.testDirectories),
        )

    def test(
        self,
        *,
        config: RepositoryConfigDocument,
        configuration: AdapterConfiguration,
        paths: Sequence[Path] = (),
        ci: bool = False,
        skipped_tiers: Sequence[str] = (),
        isolated_tiers: Sequence[str] = (),
    ) -> Command | None:
        """Build the test execution command for the selected paths.

        Every run is distributed across the machine's cores, narrowed or
        not. This used to tier on the selection -- `-n auto` for an empty
        `paths` and one process for anything else -- on the measurement that
        a worker costs about a tenth of a second to start and collect, so 32
        of them floor a run at roughly three seconds: paid once against a
        full suite's eighty seconds of work, and paid against two tenths of a
        second by a single test file.

        The tier was dropped because `paths` stopped meaning "a selection".
        A repository that pins others is run over the roots it declares as
        its own, named by its caller so the run stops at each pinned
        checkout, and those are its whole suite -- which one process took 64
        seconds over
        and every core took 25. Telling the two apart means a parameter
        saying what the paths are, and an adapter is a poor place to hold a
        distinction its caller has to keep explaining to it.

        So the floor is paid on every run: 3.2 seconds against 0.6 for a
        two-test file on an idle machine. That is the price of one rule
        instead of two, and it is the rule a reader can predict from the
        command alone.

        A tier the run does not collect is left out by directory, with one
        ignore pattern per tier (`skipped_tier_arguments`), so the selection
        is pytest's own and a path named outright still runs.

        A tier the repository declares isolated is held to starting no
        process by a plugin loaded into the run (`pytest_plugins/
        tier_isolation.py`). The adapter is never installed into a suite's
        environment, so the plugin cannot be named to `python -m pytest`:
        the run is started through one line that puts the plugin's
        directory on the import path and then hands over to pytest with the
        same arguments, which the distributed workers inherit.

        A run handed no path is kept out of what git ignores by a second
        plugin (`pytest_plugins/git_ignored.py`). Such a run collects from
        wherever the repository's own configuration starts it, and a
        repository naming nowhere is collected from its root, where the
        libraries it vendored and the adapter it resolved sit with tests of
        their own.
        """
        del config
        # `ci` is deliberately not a second axis. `-n auto` asks the machine
        # it is running on how many cores it has, which is exactly the number
        # a CI branch would otherwise have to name and get wrong -- 32 here,
        # two on a small runner. A flag can only replace a measurement with
        # a guess, so this one stays discarded on purpose.
        del ci

        # The tool's own interpreter, deliberately. In a tree whose
        # repositories are run from one environment -- the tree this is
        # developed in -- that is the environment their test dependencies
        # are installed in, and their own hold none of them: started through
        # `uv run` instead, every pinned repository's suite stopped at
        # `-n`, which its own environment has no plugin for. A repository
        # whose tests need another environment says so by declaring `test`
        # in its adapter document, as a repository outside such a tree does.
        plugins = [
            *tier_isolation_arguments(isolated_tiers=isolated_tiers),
            *git_ignored_arguments(paths=paths),
        ]
        return Command(
            executable=sys.executable,
            args=[
                *(pytest_with_plugins() if plugins else ["-m", "pytest"]),
                *plugins,
                # No override of `addopts`: it is the repository's own, and it
                # says how its suite is collected. One stood here and discarded
                # the key outright, which dropped `--pyargs` from every
                # repository naming its tests by package -- `testpaths` then
                # named a directory that does not exist, and pytest collected
                # from the root instead, vendored `lib/` and all.
                "-n",
                "auto",
                *skipped_tier_arguments(
                    skipped_tiers=skipped_tiers, configuration=configuration
                ),
                *(str(path) for path in paths),
            ],
        )

    def generate_types(
        self,
        *,
        schema: SchemaDocument,
        generate_validators: bool = False,
        generate_normalizers: bool = False,
        check: bool = False,
        type_runtime_binding: str | None = None,
    ) -> GeneratedTypeArtifact:
        """Generate types for one parsed schema document."""
        if schema.sourcePath is None:
            raise RuntimeError("Schema source path is required for type generation")

        from schema.generator import generate_python_types

        return generate_python_types(
            schema=schema,
            generate_validators=generate_validators,
            generate_normalizers=generate_normalizers,
            check=check,
            type_base_module=(
                type_runtime_binding
                if type_runtime_binding is not None
                else self.resolve_type_runtime_binding(submodule_ancestor_root=None)
            ),
        )

    def test_file_patterns(
        self, *, repo_root: Path, configuration: AdapterConfiguration
    ) -> Sequence[str]:
        """Return the file names that are test code wherever the file sits.

        `conftest.py`, and the names pytest collects -- the repository's own
        `python_files` where it states one, and the adapter's
        `testFilePatterns` where it does not.
        """
        return test_file_patterns_adapter(
            repo_root=repo_root,
            default_patterns=_spellings(globs=configuration.testFilePatterns),
        )

    def resolve_package_name(self, *, directory: Path, repo_root: Path) -> str | None:
        """Return the dotted package name of a directory, or None if it is not one."""
        return resolve_package_name_adapter(directory=directory, repo_root=repo_root)

    def resolve_app_definition_binding(
        self, *, module_root: Path, repo_root: Path
    ) -> str | None:
        """Return the import path of the module binding an application's definition."""
        return resolve_app_definition_binding_adapter(
            module_root=module_root, repo_root=repo_root
        )

    def declared_package_data(self, *, repo_root: Path) -> Sequence[PackagedFile]:
        """Return the files this repository declares as setuptools package data."""
        return declared_package_data_adapter(repo_root=repo_root)

    def declared_path_sources(self, *, repo_root: Path) -> Sequence[PathSource]:
        """Return the packages this repository's package manager takes from a path."""
        return declared_path_sources_adapter(repo_root=repo_root)

    def declared_language_requirements(
        self, *, repo_root: Path, include_development: bool = False
    ) -> Sequence[str]:
        """Return the third-party packages this repository declares it needs."""
        return declared_language_requirements_adapter(
            repo_root=repo_root, include_development=include_development
        )

    def render_vendored_requirements(
        self, *, repo_root: Path, requirements: Sequence[str]
    ) -> VendoredRequirementsFile | None:
        """Return the requirements file stating what this repository vendored."""
        return render_vendored_requirements_adapter(
            repo_root=repo_root, requirements=list(requirements)
        )

    def unresolved_package_imports(
        self,
        *,
        package_root: Path,
        package_name: str,
        configuration: AdapterConfiguration,
    ) -> Sequence[str]:
        """Return the package's imports of itself that its unpacked tree lacks."""
        return unresolved_package_imports_adapter(
            package_root=package_root,
            package_name=package_name,
            non_source_patterns=all_non_source_patterns(
                patterns=_spellings(globs=configuration.nonSourcePatterns)
            ),
        )

    def resolve_type_runtime_binding(
        self,
        *,
        submodule_ancestor_root: Path | None,
        repo_root: Path | None = None,
    ) -> str:
        """Return the Python import path generated types load TypeBase from."""
        if submodule_ancestor_root is None:
            return "type"
        posix = submodule_ancestor_root.as_posix().strip("/")
        if posix in (".", ""):
            package = self._root_package(repo_root=repo_root)
            if package is None:
                return "type"
            return f"{package}.submodule_api"
        package = self._declared_package(
            module_root=submodule_ancestor_root, repo_root=repo_root
        )
        if package is None:
            # No packaging declaration to read: the path is the package, which
            # is what it was for every repository whose root was its package.
            package = posix.replace("/", ".")
        return f"{package}.submodule_api"

    @staticmethod
    def _package_roots(*, declaration: dict[str, Any]) -> list[str]:
        """The directories a repository declares its packages are found under.

        `[tool.setuptools.packages.find] where = [...]`, which is the wrapper
        directory: a directory holding packages and nothing else.
        """
        packages = declaration.get("tool", {}).get("setuptools", {}).get("packages", {})
        if not isinstance(packages, dict):
            return []
        where = packages.get("find", {}).get("where", [])
        return [entry for entry in where if isinstance(entry, str)]

    @classmethod
    def _declared_package(
        cls, *, module_root: Path, repo_root: Path | None
    ) -> str | None:
        """The package a module root is imported as, read off its own packaging.

        A module root is a directory in some repository, and which package an
        importer reaches it as is that repository's statement rather than a fact
        about the path. `cli/packages/cli` is imported as `cli`, not as
        `cli`, because `cli/pyproject.toml` says its packages are
        found under `packages/` -- and the same file is what says so from inside
        that repository, where the very same directory is `packages/cli`.

        The nearest `pyproject.toml` above the module root decides, because that
        is the repository the module belongs to. A tree that declares no wrapper
        answers None, and the caller falls back to reading the path as the
        package, which is what it meant while every repository's root was its
        package.
        """
        if repo_root is None:
            return None
        absolute = (repo_root / module_root).resolve()
        for candidate in (absolute, *absolute.parents):
            declaration_path = candidate / "pyproject.toml"
            if not declaration_path.is_file():
                continue
            try:
                declaration = tomllib.loads(
                    declaration_path.read_text(encoding="utf-8")
                )
            except (OSError, tomllib.TOMLDecodeError):
                return None
            for where in cls._package_roots(declaration=declaration):
                base = (candidate / where).resolve()
                if absolute != base and absolute.is_relative_to(base):
                    return absolute.relative_to(base).as_posix().replace("/", ".")
            return None
        return None

    @classmethod
    def _root_package(cls, *, repo_root: Path | None) -> str | None:
        """The package a repository whose root *is* a package is imported as.

        Read from the packaging declaration rather than from the directory
        name, because the two differ wherever a distribution is named with a
        hyphen: `impl-tool` is checked out at `impl-tool` and imported as
        `impl_tool`, and a repository asked from inside itself has only its own
        files to answer with. `package-dir` mapping a package to `.` is exactly
        the statement being looked for, and a repository that makes no such
        statement has no root package -- an adapter answers None and the caller
        falls back to the bare runtime.
        """
        if repo_root is None:
            return None
        pyproject = repo_root / "pyproject.toml"
        if not pyproject.is_file():
            return None
        try:
            declaration = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError):
            return None
        package_dir = (
            declaration.get("tool", {}).get("setuptools", {}).get("package-dir", {})
        )
        if isinstance(package_dir, dict):
            for package, directory in package_dir.items():
                if isinstance(directory, str) and directory.strip("/") in (".", ""):
                    return package

        # A repository whose packages live under a wrapper declares no
        # `package-dir` at all, and it is still a package: `where = ["packages"]`
        # holding one directory is a repository that *is* that package, which is
        # what "the repository being generated" means for it. `dev_tool` was
        # resolving to the bare runtime from inside its own clone and to its
        # facade from the tree, which is the same document generated two ways.
        #
        # A wrapper holding more than one is a repository publishing more than
        # one package -- pkgmgr's application beside the store library it
        # depends on -- and the one the repository *is* is the one its
        # distribution is named for. That is a declaration too, and the only one
        # that answers the question: without it the directory count made two
        # packages ambiguous, and every submodule of the application generated
        # a bare runtime import from inside the repository and its facade import
        # from the tree.
        distribution = cls._distribution_package(declaration=declaration)
        for where in cls._package_roots(declaration=declaration):
            base = repo_root / where
            if not base.is_dir():
                continue
            packages = [
                entry.name
                for entry in sorted(base.iterdir())
                if entry.is_dir() and (entry / "__init__.py").is_file()
            ]
            if len(packages) == 1:
                return packages[0]
            if distribution in packages:
                return distribution
        return None

    @staticmethod
    def _distribution_package(*, declaration: dict[str, Any]) -> str | None:
        """The import name a distribution's own name spells, if it declares one.

        `impl-tool` is imported as `impl_tool`: a distribution name normalizes
        hyphens and dots to underscores, which is the package it is named for.
        """
        project = declaration.get("project", {})
        name = project.get("name") if isinstance(project, dict) else None
        if not isinstance(name, str) or not name.strip():
            return None
        return name.strip().lower().replace("-", "_").replace(".", "_")

    def extract_comments(self, *, path: Path) -> list[tuple[int, str]]:
        """Extract raw comment text from a source file."""
        return extract_comments_adapter(path=path)


#: What an adapter's configuration names by this package's coordinate.
core = PythonCore()
