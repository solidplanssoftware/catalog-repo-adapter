from __future__ import annotations

import os
import runpy
import subprocess
import sys
import types
from pathlib import Path
from typing import Any

import pytest
from process import Command
from repo_adapter_api import PackagedFile, PackagingInputs, RepositoryConfigDocument

from repo_adapter.__tests__.python_adapter import adapter

#: What the executable inside the artifact's directory is called here.
_EXECUTABLE = "dev-tool.exe" if os.name == "nt" else "dev-tool.bin"


def _config(**values: object) -> RepositoryConfigDocument:
    """The config as an adapter receives it: the serialized document."""
    return values


def _entrypoint(*, tmp_path: Path) -> Path:
    """Write the one thing a build needs from the tree: a file to start at."""
    entrypoint = tmp_path / "app" / "src" / "app.py"
    entrypoint.parent.mkdir(parents=True, exist_ok=True)
    if not entrypoint.is_file():
        entrypoint.write_text("", encoding="utf-8")
    return entrypoint


def _build(
    *,
    tmp_path: Path,
    packaging: PackagingInputs = PackagingInputs(),
    artifact_name: str = "dev-tool",
    form: str = "compiled",
):
    """Build a command the way the runtime does, with everything resolved.

    Of the form named, whatever the inputs were made with: most of what is
    asserted here is about the compiler, and the bundler's tests say so.
    """
    return adapter.build(
        entrypoint=_entrypoint(tmp_path=tmp_path),
        target_name="dev-tool",
        artifact_name=artifact_name,
        dist_path=tmp_path / "dist",
        scratch_path=tmp_path / "build" / ".scratch" / "dev-tool",
        packaging=packaging.model_copy(update={"form": form}),
        config=_config(),
    )


def _package(*, path: Path, modules: tuple[str, ...] = ()) -> Path:
    """Create an importable package directory holding the named modules."""
    path.mkdir(parents=True, exist_ok=True)
    (path / "__init__.py").write_text("", encoding="utf-8")
    for module in modules:
        (path / f"{module}.py").write_text("", encoding="utf-8")
    return path


def _driver(*, command: Any) -> dict[str, Any]:
    """Read the driver a build command runs, without running the compiler.

    Loaded under a name that is not the entry point's, so what it would do is
    read off the values it states and `main` is there to call.
    """
    return runpy.run_path(command.args[-1], run_name="driver")


def _option(*, command: Any, name: str) -> list[str]:
    """Every value the compiler is given for one `--name=value` option."""
    prefix = f"--{name}="
    return [
        argument[len(prefix) :]
        for argument in _driver(command=command)["COMPILER"]
        if argument.startswith(prefix)
    ]


class _Module:
    """A module as the compiler hands one to a plugin: something with a name."""

    def __init__(self, name: str) -> None:
        self._name = name

    def getFullName(self) -> str:
        return self._name


class _Told:
    """What the compiler is told about the application, asked as it asks.

    The plugin a build writes is loaded with a stand-in for the one name it
    takes from Nuitka, so what is asserted is what the compiler hears through
    each hook rather than how the file happens to be laid out.
    """

    def __init__(self, *, command: Any) -> None:
        (plugin_path,) = _option(command=command, name="user-plugin")

        class _PluginBase:
            @classmethod
            def sysexit(cls, message: str) -> None:
                raise SystemExit(message)

            def makeIncludedDataFile(
                self, source_path: str, dest_path: str, reason: str, tags: str = ""
            ) -> tuple[str, str]:
                del reason, tags
                return (source_path, dest_path)

        base = types.ModuleType("nuitka.plugins.PluginBase")
        setattr(base, "NuitkaPluginBase", _PluginBase)
        names = ("nuitka", "nuitka.plugins", "nuitka.plugins.PluginBase")
        replaced = {name: sys.modules.get(name) for name in names}
        sys.modules["nuitka"] = types.ModuleType("nuitka")
        sys.modules["nuitka.plugins"] = types.ModuleType("nuitka.plugins")
        sys.modules["nuitka.plugins.PluginBase"] = base
        try:
            self._plugin = runpy.run_path(plugin_path)["Application"]()
        finally:
            for name, module in replaced.items():
                if module is None:
                    sys.modules.pop(name, None)
                else:
                    sys.modules[name] = module

    def loaded_by_name(self, *, module: str = "__main__") -> list[str]:
        return list(self._plugin.getImplicitImports(_Module(module)))

    def files(self, *, module: str = "__main__") -> list[tuple[str, str]]:
        return list(self._plugin.considerDataFiles(_Module(module)))

    def laid_out(self, *, directory: str) -> None:
        self._plugin.onStandaloneDistributionFinished(directory)

    def follows(self, *, module: str) -> bool:
        decision = self._plugin.onModuleEncounter(
            using_module_name=None,
            module_name=module,
            module_filename=None,
            module_kind="py",
        )
        return decision is None


def test_build_compiles_the_entrypoint_it_is_given_from_a_copy_standing_alone(
    tmp_path: Path,
) -> None:
    """The compiler searches its entry script's directory before anything else.

    An application's entry point sits among its own packages, so one of them
    named like a package the application obtained would answer for it:
    dev-tool's `src/manifest` was compiled in as `manifest`, and the
    executable died on its first import. The copy is the same program, under
    the same filename, with nothing beside it.
    """
    entrypoint = _entrypoint(tmp_path=tmp_path)
    entrypoint.write_text("print('started')\n", encoding="utf-8")
    (entrypoint.parent / "manifest").mkdir()

    command = _build(tmp_path=tmp_path)

    assert command is not None
    compiled = Path(_driver(command=command)["COMPILER"][-1])
    scratch = (tmp_path / "build" / ".scratch" / "dev-tool").resolve()
    assert compiled == scratch / "nuitka" / "entry" / "app.py"
    assert compiled.read_text(encoding="utf-8") == "print('started')\n"
    assert [path.name for path in compiled.parent.iterdir()] == ["app.py"]


def test_build_names_the_artifact_it_is_told_to(tmp_path: Path) -> None:
    """The artifact's name is resolved by the caller, not derived here.

    The entrypoint of ``dev-tool`` lives in a file called ``app.py``, and the
    compiler left to itself names what it builds after that file.
    """
    command = _build(tmp_path=tmp_path)

    assert command is not None
    assert _option(command=command, name="output-filename") == [_EXECUTABLE]


def test_the_executable_is_never_named_as_a_package_beside_it_may_be(
    tmp_path: Path,
) -> None:
    """The directory holds the application's packages under their own names.

    An application's package is often named as its executable is, and a file
    and a directory of one name are one path: built on Linux, `pkgmgr` the
    executable was refused for the `pkgmgr/` its documents travel in. So the
    executable always carries a suffix, the platform's own.
    """
    command = _build(tmp_path=tmp_path, artifact_name="pkgmgr")

    assert command is not None
    (executable,) = _option(command=command, name="output-filename")
    assert executable != "pkgmgr"
    assert executable in ("pkgmgr.exe", "pkgmgr.bin")


def test_the_artifact_is_one_file_in_a_directory_named_for_it(
    tmp_path: Path,
) -> None:
    """One file a client can copy anywhere, in the directory a build is read as.

    The owner's ruling of 2026-10-18: what a client is handed is one portable
    executable, not the directory it runs out of.
    """
    command = _build(tmp_path=tmp_path)

    assert command is not None
    driver = _driver(command=command)
    assert "--onefile" in driver["COMPILER"]
    assert "--standalone" not in driver["COMPILER"]
    artifact = (tmp_path / "dist").resolve() / "dev-tool"
    assert driver["ARTIFACT"] == str(artifact)
    assert driver["PLACED"] == str(artifact / _EXECUTABLE)


def test_what_one_file_unpacks_is_kept_and_found_again(tmp_path: Path) -> None:
    """Unpacked once under the user's cache, in a directory of this build's own.

    No part of the path names the run, so Nuitka keeps what it unpacked and
    checks it on the next start rather than unpacking it again; and the
    build's own name in it keeps two builds of one application apart.
    """
    first = _option(
        command=_build(tmp_path=tmp_path / "a"), name="onefile-tempdir-spec"
    )
    second = _option(
        command=_build(tmp_path=tmp_path / "b"), name="onefile-tempdir-spec"
    )

    ((spec,), (other,)) = (first, second)
    under, application, build = spec.split("/")
    assert (under, application) == ("{CACHE_DIR}", "dev-tool-onefile")
    assert "{PID}" not in spec and "{TIME" not in spec and "{RANDOM}" not in spec
    assert build and other.split("/")[-1] != build


def test_build_keeps_its_intermediates_under_the_scratch_path_it_is_given(
    tmp_path: Path,
) -> None:
    """The work tree and the generated files are Nuitka's; the root is not.

    The compiler writes its intermediates beside its output, so it is pointed
    at the scratch path and what it builds there is moved out afterwards.
    """
    command = _build(tmp_path=tmp_path)
    scratch = (tmp_path / "build" / ".scratch" / "dev-tool").resolve()

    assert command is not None
    assert _option(command=command, name="output-dir") == [str(scratch / "work")]
    assert _driver(command=command)["BUILT"] == str(scratch / "work" / _EXECUTABLE)
    assert command.args[-1] == str(scratch / "nuitka" / "build.py")
    assert _option(command=command, name="user-plugin") == [
        str(scratch / "nuitka" / "application.py")
    ]
    assert Path(command.args[-1]).is_file()


def test_build_drops_an_executable_suffix_from_the_directory_s_name(
    tmp_path: Path,
) -> None:
    """A name that arrived as ``dev.exe`` names the executable.

    The caller keeps the filename it was asked for verbatim, because only the
    packager knows what it does with an extension; this is where that
    knowledge lives. The directory is ``dev``, and the executable inside it
    takes the suffix where the platform wants one.
    """
    command = _build(tmp_path=tmp_path, artifact_name="dev.exe")

    assert command is not None
    assert _driver(command=command)["ARTIFACT"] == str(
        (tmp_path / "dist").resolve() / "dev"
    )
    assert _option(command=command, name="output-filename") == [
        "dev.exe" if os.name == "nt" else "dev.bin"
    ]


def test_build_says_what_the_application_needs_in_a_file_and_not_the_command(
    tmp_path: Path,
) -> None:
    """The caller states what the application is; the spelling is decided here.

    In a file, because a command line has a length the platform sets and an
    application names its start-up documents one by one: the command is an
    interpreter and the driver, and the compiler's is what it is told to
    read.
    """
    data_file = tmp_path / "dev.app.yml"
    data_file.write_text("name: dev", encoding="utf-8")

    command = _build(
        tmp_path=tmp_path,
        packaging=PackagingInputs(
            modulesLoadedByName=["yaml"],
            files=[PackagedFile(source=data_file, destination="dev_tool")],
        ),
    )

    assert command is not None
    told = _Told(command=command)
    assert told.loaded_by_name() == ["yaml"]
    # A file is carried to a directory, and the compiler is told the path.
    assert told.files() == [(str(data_file.resolve()), "dev_tool/dev.app.yml")]
    stated = [*command.args, *_driver(command=command)["COMPILER"]]
    assert not any("dev.app.yml" in argument for argument in stated)
    assert "yaml" not in stated


def test_only_the_entry_point_is_said_to_load_what_is_loaded_by_name(
    tmp_path: Path,
) -> None:
    """Named once, against the one module every build has."""
    data_file = tmp_path / "dev.app.yml"
    data_file.write_text("name: dev", encoding="utf-8")
    command = _build(
        tmp_path=tmp_path,
        packaging=PackagingInputs(
            modulesLoadedByName=["yaml"],
            files=[PackagedFile(source=data_file, destination="dev_tool")],
        ),
    )

    assert command is not None
    told = _Told(command=command)
    assert told.loaded_by_name(module="cli.runner") == []
    assert told.files(module="cli.runner") == []


def test_build_searches_where_the_obtained_packages_are_imported_from(
    tmp_path: Path,
) -> None:
    """Nuitka resolves a name the way its own interpreter would.

    That interpreter's environment holds what was installed and none of what
    the repository fetched into its own tree, so the directories are put on
    the path the compiler is started with.
    """
    command = _build(
        tmp_path=tmp_path,
        packaging=PackagingInputs(obtainedPackageRoots=[tmp_path / "lib"]),
    )

    assert command is not None
    assert _driver(command=command)["SEARCHED"] == [str((tmp_path / "lib").resolve())]


def test_a_package_loaded_by_name_is_enumerated_from_where_it_was_obtained(
    tmp_path: Path,
) -> None:
    """Every module at any depth is named outright, read off the directory."""
    registry = _package(path=tmp_path / "lib" / "cli" / "src" / "registry")
    _package(path=tmp_path / "lib" / "cli")
    _package(path=tmp_path / "lib" / "cli" / "src")
    _package(path=registry / "update", modules=("command",))
    # A group of command packages kept in a directory with no marker of its
    # own: the interpreter imports through it, so what it holds is named.
    _package(path=registry / "development" / "install", modules=("command",))
    (registry / "development" / ".cache").mkdir()
    (registry / "development" / ".cache" / "stale.py").write_text("", encoding="utf-8")

    command = _build(
        tmp_path=tmp_path,
        packaging=PackagingInputs(
            packagesLoadedByName=["cli.src.registry"],
            obtainedPackageRoots=[tmp_path / "lib"],
        ),
    )

    assert command is not None
    assert _Told(command=command).loaded_by_name() == [
        "cli.src.registry",
        "cli.src.registry.development.install",
        "cli.src.registry.development.install.command",
        "cli.src.registry.update",
        "cli.src.registry.update.command",
    ]
    assert _option(command=command, name="include-package") == []


def test_a_package_of_the_repository_s_own_is_found_where_it_declares_them(
    tmp_path: Path,
) -> None:
    """`packages/app` is imported as `app`, because the repository says so."""
    (tmp_path / "pyproject.toml").write_text(
        '[tool.setuptools.packages.find]\nwhere = ["packages"]\n', encoding="utf-8"
    )
    entrypoint = tmp_path / "packages" / "app" / "src" / "app.py"
    _package(path=tmp_path / "packages" / "app")
    _package(path=tmp_path / "packages" / "app" / "src")
    _package(path=tmp_path / "packages" / "app" / "src" / "registry", modules=("run",))
    entrypoint.write_text("", encoding="utf-8")

    command = adapter.build(
        entrypoint=entrypoint,
        target_name="app",
        artifact_name="app",
        dist_path=tmp_path / "dist",
        scratch_path=tmp_path / "build" / ".scratch" / "app",
        packaging=PackagingInputs(
            packagesLoadedByName=["app.src.registry"], form="compiled"
        ),
        config=_config(),
    )

    assert command is not None
    assert _Told(command=command).loaded_by_name() == [
        "app.src.registry",
        "app.src.registry.run",
    ]


def test_build_keeps_out_what_is_not_part_of_the_application(tmp_path: Path) -> None:
    """A test package sits beside the code and is reached wherever that is.

    The compiler is told not to follow into it, whichever import reaches it,
    and it is passed when a package loaded by name above it is enumerated.
    """
    registry = _package(path=tmp_path / "lib" / "cli", modules=("runner",))
    _package(path=registry / "__tests__", modules=("test_runner",))
    _package(path=registry / "__tests__" / "__unit__", modules=("test_deep",))

    command = _build(
        tmp_path=tmp_path,
        packaging=PackagingInputs(
            packagesLoadedByName=["cli"],
            nonApplicationPackages=["cli.__tests__", "dev_tool.src.__tests__"],
            obtainedPackageRoots=[tmp_path / "lib"],
        ),
    )

    assert command is not None
    told = _Told(command=command)
    assert told.loaded_by_name() == ["cli", "cli.runner"]
    assert not told.follows(module="cli.__tests__")
    assert not told.follows(module="cli.__tests__.__unit__.test_deep")
    assert not told.follows(module="dev_tool.src.__tests__.test_app")
    assert told.follows(module="cli.runner")
    # A package is excluded by its name, not by a name that starts like it.
    assert told.follows(module="cli.__tests__helpers")


def test_a_test_directory_that_is_no_package_is_passed(tmp_path: Path) -> None:
    """It has no name to be excluded by, and it is still not the application.

    A directory with no marker is walked through, since a registry keeps a
    group of commands in one -- which named every test in a marker-less
    `__tests__` as a module of the application, and compiled the test runner
    those tests import into the executable.
    """
    registry = _package(path=tmp_path / "lib" / "cli", modules=("runner",))
    (registry / "__tests__" / "__unit__").mkdir(parents=True)
    (registry / "__tests__" / "__unit__" / "test_runner.py").write_text(
        "import pytest\n", encoding="utf-8"
    )

    command = _build(
        tmp_path=tmp_path,
        packaging=PackagingInputs(
            packagesLoadedByName=["cli"],
            obtainedPackageRoots=[tmp_path / "lib"],
        ),
    )

    assert command is not None
    assert _Told(command=command).loaded_by_name() == ["cli", "cli.runner"]


def test_a_package_found_nowhere_searched_is_left_to_the_compiler(
    tmp_path: Path,
) -> None:
    """One the compiler's own environment holds, installed rather than obtained."""
    command = _build(
        tmp_path=tmp_path,
        packaging=PackagingInputs(
            packagesLoadedByName=["installed.registry", "installed.__tests__"],
            nonApplicationPackages=["installed.__tests__"],
        ),
    )

    assert command is not None
    # An exclusion outranks it: the compiler is not told to include a package
    # it is also told never to follow.
    assert _option(command=command, name="include-package") == ["installed.registry"]
    assert _Told(command=command).loaded_by_name() == []


def test_build_declares_nothing_of_its_own(tmp_path: Path) -> None:
    """An empty declaration produces a build with no extra inputs at all.

    An adapter that added its own guesses here would be discovering a tree's
    layout again, one default at a time.
    """
    command = _build(tmp_path=tmp_path)

    assert command is not None
    told = _Told(command=command)
    assert _driver(command=command)["SEARCHED"] == []
    assert told.loaded_by_name() == []
    assert told.files() == []
    assert told.follows(module="anything.__tests__")
    assert _option(command=command, name="include-package") == []


def test_the_compiler_reads_an_environment_without_the_development_group(
    tmp_path: Path,
) -> None:
    """An application is built from what it runs on, not what it is developed with.

    Nuitka compiles whatever an import anywhere in the graph resolves, a
    third-party package's optional import of a test runner included. The
    environment is made for the run, because the repository's own keeps
    whatever an earlier run installed into it.
    """
    command = _build(tmp_path=tmp_path)

    assert command is not None
    assert command.executable == "uv"
    assert command.args[:-1] == [
        "run",
        "--isolated",
        "--no-dev",
        "--with",
        "nuitka[onefile]==4.3",
        "python",
    ]


def _compiler(
    *, monkeypatch: pytest.MonkeyPatch, returncode: int
) -> list[dict[str, str]]:
    """Stand in for the compiler: record how it was started, and build if asked."""
    started: list[dict[str, str]] = []

    def _run(arguments: list[str], *, env: dict[str, str], check: bool) -> Any:
        del check
        started.append(env)
        if returncode == 0:
            (output,) = [
                argument.partition("=")[2]
                for argument in arguments
                if argument.startswith("--output-dir=")
            ]
            Path(output).mkdir(parents=True)
            (Path(output) / _EXECUTABLE).write_text("compiled", encoding="utf-8")
        return subprocess.CompletedProcess(arguments, returncode)

    monkeypatch.setattr(subprocess, "run", _run)
    return started


def test_the_driver_replaces_the_artifact_with_what_the_compiler_built(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """What an earlier build left under the name does not outlive this one.

    Neither the directory, whose contents would otherwise be merged into, nor
    a single file an earlier packager wrote there, which a reader looking for
    the artifact would find first.
    """
    command = _build(
        tmp_path=tmp_path,
        packaging=PackagingInputs(obtainedPackageRoots=[tmp_path / "lib"]),
    )
    assert command is not None
    artifact = tmp_path / "dist" / "dev-tool"
    artifact.mkdir(parents=True)
    (artifact / "stale.dll").write_text("stale", encoding="utf-8")
    (tmp_path / "dist" / "dev-tool.exe").write_text("one file", encoding="utf-8")
    monkeypatch.setenv("PYTHONPATH", "already-there")
    started = _compiler(monkeypatch=monkeypatch, returncode=0)

    assert _driver(command=command)["main"]() == 0

    assert sorted(path.name for path in (tmp_path / "dist").iterdir()) == ["dev-tool"]
    assert sorted(path.name for path in artifact.iterdir()) == [_EXECUTABLE]
    assert started[0]["PYTHONPATH"].split(os.pathsep) == [
        str((tmp_path / "lib").resolve()),
        "already-there",
    ]


def test_a_compile_that_failed_leaves_the_artifact_as_it_was(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The compiler's own exit code is the build's, and nothing is moved."""
    command = _build(tmp_path=tmp_path)
    assert command is not None
    artifact = tmp_path / "dist" / "dev-tool"
    artifact.mkdir(parents=True)
    (artifact / _EXECUTABLE).write_text("the last one", encoding="utf-8")
    _compiler(monkeypatch=monkeypatch, returncode=3)

    assert _driver(command=command)["main"]() == 3

    assert (artifact / _EXECUTABLE).read_text(encoding="utf-8") == "the last one"


class _Spec:
    """What the bundler is told about the application, read as it reads it.

    The spec a build writes is run with a stand-in for each name PyInstaller
    defines in a spec's namespace, and each records what it was called with,
    so what is asserted is what the packager would be handed rather than how
    the file happens to be laid out.
    """

    def __init__(self, *, command: Any) -> None:
        driver = _driver(command=command)
        (spec_path,) = [
            argument for argument in driver["COMPILER"] if argument.endswith(".spec")
        ]
        self.path = Path(spec_path)
        self.calls: dict[str, dict[str, Any]] = {}
        self.collected: list[str] = []

        def recorder(name: str) -> Any:
            def record(*args: Any, **kwargs: Any) -> Any:
                self.calls[name] = {"args": list(args), **kwargs}
                # What the next call reads off this one's result.
                return types.SimpleNamespace(pure=[], scripts=[], binaries=[], datas=[])

            return record

        def collect_submodules(package: str) -> list[str]:
            self.collected.append(package)
            return [f"{package}.collected"]

        hooks = types.ModuleType("PyInstaller.utils.hooks")
        setattr(hooks, "collect_submodules", collect_submodules)
        names = ("PyInstaller", "PyInstaller.utils", "PyInstaller.utils.hooks")
        replaced = {name: sys.modules.get(name) for name in names}
        sys.modules["PyInstaller"] = types.ModuleType("PyInstaller")
        sys.modules["PyInstaller.utils"] = types.ModuleType("PyInstaller.utils")
        sys.modules["PyInstaller.utils.hooks"] = hooks
        try:
            runpy.run_path(
                spec_path,
                init_globals={
                    name: recorder(name)
                    for name in ("Analysis", "PYZ", "EXE", "COLLECT")
                },
            )
        finally:
            for name, module in replaced.items():
                if module is None:
                    sys.modules.pop(name, None)
                else:
                    sys.modules[name] = module


def test_a_bundled_build_runs_the_bundler_without_the_development_group(
    tmp_path: Path,
) -> None:
    """The bundler reads the environment the compiler reads, for the same reason."""
    command = _build(tmp_path=tmp_path, form="bundled")

    assert command is not None
    assert command.executable == "uv"
    assert command.args[:-1] == [
        "run",
        "--isolated",
        "--no-dev",
        "--with",
        "pyinstaller==6.22.3",
        "python",
    ]
    scratch = (tmp_path / "build" / ".scratch" / "dev-tool").resolve()
    assert command.args[-1] == str(scratch / "pyinstaller" / "build.py")
    compiler = _driver(command=command)["COMPILER"]
    assert compiler[:2] == ["-m", "PyInstaller"]
    assert f"--distpath={scratch / 'work' / 'dist'}" in compiler
    assert f"--workpath={scratch / 'work' / 'build'}" in compiler


def test_either_form_leaves_the_same_artifact_where_it_was_asked_for(
    tmp_path: Path,
) -> None:
    """One directory, one name, one executable inside it, whichever packager.

    Everything downstream reads the artifact -- the build catalog, the
    toolchain's install, the start-up check -- and none of it asks which
    packager made it. A bundle carries its files beside the executable and a
    compile packs them into it, which is all that tells the two apart.
    """
    compiled = _driver(command=_build(tmp_path=tmp_path / "c", form="compiled"))
    bundled_command = _build(tmp_path=tmp_path / "b", form="bundled")
    bundled = _driver(command=bundled_command)
    spec = _Spec(command=bundled_command)

    assert Path(bundled["ARTIFACT"]).name == Path(compiled["ARTIFACT"]).name
    assert bundled["ARTIFACT"] == str((tmp_path / "b" / "dist").resolve() / "dev-tool")
    scratch = (tmp_path / "b" / "build" / ".scratch" / "dev-tool").resolve()
    assert bundled["BUILT"] == str(scratch / "work" / "dist" / "dev-tool")
    assert spec.calls["EXE"]["name"] == _EXECUTABLE
    assert spec.calls["EXE"]["exclude_binaries"] is True
    # Everything it carries beside the executable, not under a directory of
    # the packager's own: a file sits where it sits in the compiled artifact.
    assert spec.calls["EXE"]["contents_directory"] == "."
    assert spec.calls["COLLECT"]["name"] == "dev-tool"


def test_a_bundled_build_starts_from_a_copy_of_the_entry_point_standing_alone(
    tmp_path: Path,
) -> None:
    """The bundler searches its entry script's directory first, as the compiler does."""
    entrypoint = _entrypoint(tmp_path=tmp_path)
    entrypoint.write_text("print('started')\n", encoding="utf-8")
    (entrypoint.parent / "manifest").mkdir()

    spec = _Spec(command=_build(tmp_path=tmp_path, form="bundled"))

    (entry,) = spec.calls["Analysis"]["args"][0]
    scratch = (tmp_path / "build" / ".scratch" / "dev-tool").resolve()
    assert Path(entry) == scratch / "pyinstaller" / "entry" / "app.py"
    assert Path(entry).read_text(encoding="utf-8") == "print('started')\n"
    assert [path.name for path in Path(entry).parent.iterdir()] == ["app.py"]


def test_a_bundled_build_is_told_what_the_compiled_one_is_told(
    tmp_path: Path,
) -> None:
    """The same inputs, in the bundler's spelling.

    What is loaded by name is imported, a package loaded by name is
    enumerated from where it was obtained, a file goes to the directory the
    application looks in, an excluded package is not found, and the
    directories obtained packages sit in are searched.
    """
    lib = tmp_path / "lib"
    _package(path=lib / "obtained", modules=("one",))
    _package(path=lib / "obtained" / "__tests__", modules=("test_one",))
    data_file = tmp_path / "dev.app.yml"
    data_file.write_text("name: dev", encoding="utf-8")

    spec = _Spec(
        command=_build(
            tmp_path=tmp_path,
            form="bundled",
            packaging=PackagingInputs(
                modulesLoadedByName=["yaml"],
                packagesLoadedByName=["obtained", "installed"],
                files=[PackagedFile(source=data_file, destination="dev_tool")],
                nonApplicationPackages=["obtained.__tests__"],
                obtainedPackageRoots=[lib],
            ),
        )
    )

    analysis = spec.calls["Analysis"]
    assert analysis["pathex"] == [str(lib.resolve())]
    assert analysis["datas"] == [(str(data_file.resolve()), "dev_tool")]
    assert analysis["hiddenimports"] == [
        "yaml",
        "obtained",
        "obtained.one",
        "installed.collected",
    ]
    assert spec.collected == ["installed"]
    assert analysis["excludes"][0] == "obtained.__tests__"


def test_the_bundler_s_own_setuptools_is_kept_out_unless_the_repository_asks_for_it(
    tmp_path: Path,
) -> None:
    """PyInstaller brings setuptools into every environment it analyses.

    It is the packager's, not the application's, and is left out -- except
    where the repository declares it, which means the application uses it.
    """
    bundled = _Spec(command=_build(tmp_path=tmp_path / "a", form="bundled"))
    assert set(bundled.calls["Analysis"]["excludes"]) == {
        "setuptools",
        "pkg_resources",
        "_distutils_hack",
    }

    declaring = tmp_path / "b"
    (declaring / "app").mkdir(parents=True)
    (declaring / "app" / "pyproject.toml").write_text(
        '[project]\nname = "app"\ndependencies = ["setuptools>=70"]\n',
        encoding="utf-8",
    )
    declared = _Spec(command=_build(tmp_path=declaring, form="bundled"))
    assert declared.calls["Analysis"]["excludes"] == []


def test_the_signing_command_runs_on_what_was_laid_out_before_it_is_packed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A binary inside the one file is signed there or never.

    Run with the directory appended; a failure stops the build.
    """
    command = _build(
        tmp_path=tmp_path,
        packaging=PackagingInputs(
            signCommand=Command(executable="pwsh", args=["-File", "sign.ps1"])
        ),
    )
    assert command is not None
    told = _Told(command=command)
    ran: list[list[str]] = []
    returncode = 0

    def _run(arguments: list[str], *, check: bool) -> Any:
        del check
        ran.append(arguments)
        return subprocess.CompletedProcess(arguments, returncode)

    monkeypatch.setattr(subprocess, "run", _run)

    told.laid_out(directory="laid-out")
    assert ran == [["pwsh", "-File", "sign.ps1", "laid-out"]]

    returncode = 4
    with pytest.raises(SystemExit, match="exit 4"):
        told.laid_out(directory="laid-out")


def test_nothing_is_signed_where_no_command_is_named(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    command = _build(tmp_path=tmp_path)
    assert command is not None
    told = _Told(command=command)
    monkeypatch.setattr(
        subprocess, "run", lambda *args, **kwargs: pytest.fail("signed")
    )

    told.laid_out(directory="laid-out")
