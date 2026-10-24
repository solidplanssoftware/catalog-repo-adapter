from __future__ import annotations

import os
from collections.abc import Sequence
from pathlib import Path, PurePosixPath

from process import Command, argv
from repo_adapter_api import PackagingInputs, is_non_source

from ..tree_shape import declares_requirement, own_package_roots

# What the executable is to be, as the build is told: the interpreter and the
# application's bytecode put together, or the application compiled to native
# code. Each is one packager's work here, and the artifact is a directory
# named for the executable from either: the bundler's holds the executable
# and everything it runs beside, the compiler's the one file it packed all of
# that into.
_BUNDLED = "bundled"
_COMPILED = "compiled"

# What a Windows executable's filename ends in. Neither packager is left to
# name the executable, so the suffix is put on here where the platform wants
# one -- and taken off a name that arrived carrying it, since the artifact is
# a directory named for the executable, which carries none.
_EXECUTABLE_SUFFIX = ".exe"
_WINDOWS = "nt"

# What the executable's filename ends in everywhere else. A standalone
# directory holds the executable beside the application's packages, each in a
# directory of its own name, and an application's package is often named as
# its executable is: `pkgmgr` the file and `pkgmgr/` the directory are one
# path, which neither packager can write. Windows never meets it, since the
# suffix above keeps the two apart; this is the suffix Nuitka itself gives an
# executable there for the same reason, stated rather than left to it so the
# name is the same whichever name collides and whichever packager wrote it.
_POSIX_EXECUTABLE_SUFFIX = ".bin"

# Where a compiled executable unpacks what it packed, on its first start, and
# finds it again on every start after: the user's cache directory as Nuitka
# resolves it at run time (the local application data folder Windows names for
# the user, which follows `USERPROFILE` and not `LOCALAPPDATA`, and
# `XDG_CACHE_HOME` or `~/.cache` elsewhere), a directory named for the application, and one named
# for the build. No part of it names the run, so Nuitka keeps what it unpacked
# rather than removing it at exit, and on each start checks every file there
# against the one it carries, rewriting any that differs.
_UNPACKED_UNDER = "{CACHE_DIR}"
_UNPACKED_SUFFIX = "-onefile"

# The distribution PyInstaller depends on, and the top-level modules it
# installs: what the packager's own environment holds whether or not the
# application being built asked for it.
_PACKAGER_DISTRIBUTION = "setuptools"
_PACKAGER_MODULES = ("setuptools", "pkg_resources", "_distutils_hack")

# Which packager makes each form, at the version it is pinned to. A packager
# is part of what a build is: a client's executable compiled on one runner
# and its sibling on another are one release only where both were compiled
# by the same compiler, so the version is stated here rather than taken as
# whatever the index answers on the day. Moved on purpose, and measured.
# The compiler's `onefile` extra is what compresses the packed file: without
# it Nuitka packs every file as it is, and says so.
_COMPILER = "nuitka[onefile]==4.3"
_BUNDLER = "pyinstaller==6.22.3"

_PACKAGE_MARKER = "__init__.py"
_MODULE_SUFFIX = ".py"
_COMPILER_CACHE = "__pycache__"


def _build_name(*, artifact_name: str) -> str:
    """Return the name the artifact's directory takes, and its executable's stem."""
    if artifact_name.lower().endswith(_EXECUTABLE_SUFFIX):
        return artifact_name[: -len(_EXECUTABLE_SUFFIX)]
    return artifact_name


def _package_directory(*, package: str, roots: Sequence[Path]) -> Path | None:
    """Where a package named by its dotted name sits, under the first root holding it."""
    for root in roots:
        directory = root.joinpath(*package.split("."))
        if (directory / _PACKAGE_MARKER).is_file():
            return directory
    return None


def _is_excluded(*, module: str, excluded: Sequence[str]) -> bool:
    """Whether a module is one of the excluded packages or sits beneath one."""
    return any(module == name or module.startswith(f"{name}.") for name in excluded)


def _modules_of(
    *,
    package: str,
    directory: Path,
    excluded: Sequence[str],
    test_directories: Sequence[str],
) -> list[str]:
    """Every module of a package, at any depth, that is part of the application.

    Read off the directory rather than by importing the package, which is
    what the packager's own enumeration does: an import runs the package at
    build time, in an environment that is not the application's, and a
    package that cannot be imported there is silently left out with
    everything beneath it. An excluded package is passed here rather than
    enumerated and then refused, so nothing is named that the build was also
    told to leave out.

    A directory without the package marker is still walked. The interpreter
    imports through one as a namespace portion, and a registry keeps a group
    of command packages in exactly such a directory -- so what sits beneath
    it is named, and the directory itself, which holds no module of its own
    to name, is not.

    A test directory without the marker is the exception, and is passed. An
    exclusion names a package, and a directory that is no package has no name
    to be excluded by -- so walking through one named every test in it as
    part of the application, and the test runner those tests import came
    along into the executable.
    """
    if _is_excluded(module=package, excluded=excluded):
        return []
    is_package = (directory / _PACKAGE_MARKER).is_file()
    if not is_package and is_non_source(
        relative_path=directory.name, patterns=test_directories
    ):
        return []
    modules = [package] if is_package else []
    for entry in sorted(directory.iterdir()):
        if entry.is_dir():
            if entry.name != _COMPILER_CACHE and not entry.name.startswith("."):
                modules.extend(
                    _modules_of(
                        package=f"{package}.{entry.name}",
                        directory=entry,
                        excluded=excluded,
                        test_directories=test_directories,
                    )
                )
            continue
        if entry.suffix != _MODULE_SUFFIX or entry.name == _PACKAGE_MARKER:
            continue
        module = f"{package}.{entry.stem}"
        if not _is_excluded(module=module, excluded=excluded):
            modules.append(module)
    return modules


def _listing(*, name: str, values: Sequence[object]) -> str:
    """One generated variable holding a list, an element to a line."""
    body = "".join(f"    {value!r},\n" for value in values)
    return f"{name} = [\n{body}]\n"


def _loaded_by_name(
    *,
    entrypoint: Path,
    packaging: PackagingInputs,
    test_directories: Sequence[str],
) -> tuple[list[str], list[str]]:
    """Every module loaded by name, and the packages found nowhere searched.

    A package loaded by name is enumerated here, from the directory it was
    obtained into or the one the repository declares its own packages in, so
    each of its modules is named outright and what sits beneath an excluded
    package never is. One found under neither is a package the packager's own
    environment holds, installed rather than obtained: it is left to the
    packager's enumeration, and named apart for that reason.
    """
    roots = [
        *(root.resolve() for root in packaging.obtainedPackageRoots),
        *own_package_roots(directory=entrypoint.resolve().parent),
    ]
    named: list[str] = list(packaging.modulesLoadedByName)
    unlocated: list[str] = []
    for package in packaging.packagesLoadedByName:
        directory = _package_directory(package=package, roots=roots)
        if directory is None:
            if not _is_excluded(
                module=package, excluded=packaging.nonApplicationPackages
            ):
                unlocated.append(package)
            continue
        named.extend(
            _modules_of(
                package=package,
                directory=directory,
                excluded=packaging.nonApplicationPackages,
                test_directories=test_directories,
            )
        )
    return list(dict.fromkeys(named)), unlocated


_APPLICATION_HEADER = '''\
# Generated by the Python repo adapter for one build. Do not edit.
"""What one application is where its import graph is wrong about it.

A Nuitka plugin, which is how the compiler is told at any length: the modules
the application loads by name, the packages that are no part of it, the files
it reads once it is running, and the command, if any, that signs what the
compiler laid out before it packs it into one file.
"""

import subprocess

from nuitka.plugins.PluginBase import NuitkaPluginBase

'''

_APPLICATION_BODY = '''

class Application(NuitkaPluginBase):
    """Say the three lists above in the compiler's own terms."""

    plugin_name = "application"
    plugin_desc = "What the application is where its import graph is wrong about it."

    def getImplicitImports(self, module):
        """Name what is loaded by name as imports of the entry point."""
        if module.getFullName() == "__main__":
            yield from LOADED_BY_NAME

    def onModuleEncounter(
        self, using_module_name, module_name, module_filename, module_kind
    ):
        """Refuse a module in or beneath an excluded package, whoever reaches it."""
        del using_module_name, module_filename, module_kind
        name = str(module_name)
        for package in EXCLUDED:
            if name == package or name.startswith(package + "."):
                return False, "'%s' is not part of the application" % package
        return None

    def considerDataFiles(self, module):
        """Carry each file to where the running application looks for it."""
        if module.getFullName() == "__main__":
            for source, destination in FILES:
                yield self.makeIncludedDataFile(
                    source_path=source,
                    dest_path=destination,
                    reason="read by the application once it is running",
                )

    def onStandaloneDistributionFinished(self, dist_dir):
        """Sign every binary the compiler laid out, before it packs them.

        What the packed file unpacks on a machine is what it carried, so a
        binary is signed here or never: run the signing command with the
        directory appended, and stop the build where it fails.
        """
        if not SIGN:
            return
        completed = subprocess.run([*SIGN, dist_dir], check=False)
        if completed.returncode != 0:
            self.sysexit(
                "signing what was laid out in '%s' failed with exit %d"
                % (dist_dir, completed.returncode)
            )
'''


def _application(*, named: Sequence[str], packaging: PackagingInputs) -> str:
    """Render what the application needs as a Nuitka plugin.

    The inputs say what the application is; how that is said to this
    compiler is decided here and nowhere else. Nuitka compiles an import
    graph, so a module loaded by name is one it has to be told the entry
    point imports, and so is every module of a package loaded by name,
    enumerated before this is called. A file read at run time is data it has
    to carry beside the executable, at the path the application looks for it
    under. A package that is not part of the application is one it is told
    not to follow, whichever import reaches it -- which takes the package's
    submodules with it, and leaves an import of one failing at run time with
    the compiler's own statement that it was excluded. Another compiler
    would be told the same facts in other spellings, or not told one it
    works out for itself.

    The signing command is run on the directory the compiler lays out, once
    it is whole and before the compiler packs it into one file
    (``onStandaloneDistributionFinished``): every binary the file unpacks is
    then one the command signed, and the file itself is signed afterwards by
    whoever signs the artifact. Where none is asked for, nothing is run.

    A file rather than a command line. A command line has a length the
    platform sets, an application names its start-up documents and its
    command modules one by one, and one that obtained another application
    names several hundred of each: a build told on the command line stops
    being startable before it stops being correct. A plugin is the one way
    Nuitka reads a list of any length, and it lets a package's modules be
    named outright rather than handed to ``--include-package``, which walks
    into a test directory that carries no package marker.

    Nothing is added to what arrived.
    """
    files = [
        (
            str(entry.source.resolve()),
            (PurePosixPath(entry.destination) / entry.source.name).as_posix(),
        )
        for entry in packaging.files
    ]
    return "".join(
        [
            _APPLICATION_HEADER,
            _listing(name="LOADED_BY_NAME", values=named),
            _listing(name="EXCLUDED", values=packaging.nonApplicationPackages),
            _listing(name="FILES", values=files),
            _listing(
                name="SIGN",
                values=argv(command=packaging.signCommand)
                if packaging.signCommand is not None
                else [],
            ),
            _APPLICATION_BODY,
        ]
    )


_DRIVER_HEADER = '''\
# Generated by the Python repo adapter for one build. Do not edit.
"""Run one application's packager and put what it built where it goes."""

import os
import shutil
import subprocess
import sys

'''

_DRIVER_BODY = '''

def main() -> int:
    """Run the packager, then replace the artifact with what it built."""
    environment = dict(os.environ)
    searched = [*SEARCHED, *filter(None, [environment.get("PYTHONPATH")])]
    if searched:
        environment["PYTHONPATH"] = os.pathsep.join(searched)
    completed = subprocess.run(
        [sys.executable, *COMPILER], env=environment, check=False
    )
    if completed.returncode != 0:
        return completed.returncode
    for stale in STALE:
        if os.path.isfile(stale):
            os.remove(stale)
    if os.path.isdir(ARTIFACT):
        shutil.rmtree(ARTIFACT)
    os.makedirs(os.path.dirname(PLACED), exist_ok=True)
    shutil.move(BUILT, PLACED)
    return 0


if __name__ == "__main__":
    sys.exit(main())
'''


def _driver(
    *,
    compiler: Sequence[str],
    searched: Sequence[str],
    built: Path,
    artifact: Path,
    placed: Path | None = None,
) -> str:
    """Render the one process a build is: the packager, and where its output goes.

    The same driver for either packager, since both leave the same two
    things to it. Where the application's obtained packages are imported
    from is a directory a packager has to search, and each searches what the
    interpreter running it would: that interpreter's environment holds what
    was installed, never what the repository fetched into its own tree, so
    those directories are put on the path the packager is started with. And
    each writes what it built beside its own intermediates, so that is moved
    to where the artifact was asked for once the packager has succeeded --
    replacing the directory a previous build left, and a single file an
    earlier packager left under the same name, which a reader looking for the
    artifact would otherwise find first. ``placed`` is where in the artifact
    it goes: the artifact itself for a directory, and a path inside it for
    the one file a compile packs.
    """
    return "".join(
        [
            _DRIVER_HEADER,
            _listing(name="SEARCHED", values=searched),
            _listing(name="COMPILER", values=compiler),
            f"BUILT = {str(built)!r}\n",
            f"ARTIFACT = {str(artifact)!r}\n",
            f"PLACED = {str(placed or artifact)!r}\n",
            _listing(
                name="STALE",
                values=[str(artifact), f"{artifact}{_EXECUTABLE_SUFFIX}"],
            ),
            _DRIVER_BODY,
        ]
    )


def _spec(
    *,
    entry_path: Path,
    executable: str,
    name: str,
    named: Sequence[str],
    unlocated: Sequence[str],
    packaging: PackagingInputs,
    packager_owned: Sequence[str],
) -> str:
    """Render what the application needs as a PyInstaller spec file.

    The same facts `_application` says to Nuitka, in this packager's
    spelling. Where the obtained packages are imported from is a directory
    its analysis searches (``pathex``). A module loaded by name, and every
    module of a package loaded by name enumerated before this is called, is
    one it is told is imported (``hiddenimports``); a package loaded by name
    that sits nowhere searched is left to the packager's own enumeration
    (``collect_submodules``), as Nuitka is handed it to include. A file read
    at run time is data it carries (``datas``) to the path the application
    looks for it under, and a package that is not part of the application is
    one its analysis treats as not found (``excludes``), which takes the
    package's submodules with it whatever import reaches them.

    A spec file rather than a command line for the reason the compiler is
    given a plugin: an application that obtained another names several
    hundred modules and documents, and a command line has a length the
    platform sets.

    One directory: the executable under the name it is given and every file
    it carries beside it rather than under a directory of the packager's own
    (``contents_directory='.'``), so a data file sits at the path it sits at
    in the directory a compiled executable unpacks, and the application's
    root is the directory its entry script runs from either way.
    """
    datas = [
        (str(entry.source.resolve()), entry.destination) for entry in packaging.files
    ]
    pathex = [str(root.resolve()) for root in packaging.obtainedPackageRoots]
    return "".join(
        [
            "# -*- mode: python ; coding: utf-8 -*-\n",
            "# Generated by the Python repo adapter for one build. Do not edit.\n",
            "from PyInstaller.utils.hooks import collect_submodules\n\n",
            _listing(name="pathex", values=pathex),
            _listing(name="datas", values=datas),
            _listing(name="hiddenimports", values=named),
            _listing(
                name="excludes",
                values=[*packaging.nonApplicationPackages, *packager_owned],
            ),
            _listing(name="collected", values=unlocated),
            "for package in collected:\n",
            "    hiddenimports += collect_submodules(package)\n\n",
            "a = Analysis(\n",
            f"    [{str(entry_path)!r}],\n",
            "    pathex=pathex,\n",
            "    binaries=[],\n",
            "    datas=datas,\n",
            "    hiddenimports=hiddenimports,\n",
            "    hookspath=[],\n",
            "    hooksconfig={},\n",
            "    runtime_hooks=[],\n",
            "    excludes=excludes,\n",
            "    noarchive=False,\n",
            ")\n",
            "pyz = PYZ(a.pure)\n",
            "exe = EXE(\n",
            "    pyz,\n",
            "    a.scripts,\n",
            "    [],\n",
            "    exclude_binaries=True,\n",
            f"    name={executable!r},\n",
            "    console=True,\n",
            "    contents_directory='.',\n",
            ")\n",
            "coll = COLLECT(\n",
            "    exe,\n",
            "    a.binaries,\n",
            "    a.datas,\n",
            f"    name={name!r},\n",
            ")\n",
        ]
    )


def _standalone_entry(*, entrypoint: Path, generated: Path) -> Path:
    """A copy of the entry point standing alone in a directory of its own.

    Both packagers search the directory their entry script sits in before
    anything else, as an interpreter handed a script does, and an
    application's entry point sits among its own packages: dev-tool's
    ``src/manifest`` answered ``import manifest`` ahead of the framework
    package of that name, and the executable built without complaint and
    died on its first import. A copy is the same program, because an entry
    point runs as ``__main__`` with no package of its own and so carries no
    relative import; where the application's packages are found is where they
    are imported from, which is never the directory beside the entry point.
    """
    entry_path = generated / "entry" / entrypoint.name
    entry_path.parent.mkdir(parents=True, exist_ok=True)
    entry_path.write_bytes(entrypoint.resolve().read_bytes())
    return entry_path


def build(
    *,
    entrypoint: Path,
    artifact_name: str,
    dist_path: Path,
    scratch_path: Path,
    packaging: PackagingInputs,
    test_directories: Sequence[str],
) -> Command | None:
    """Build the command that makes one Python entrypoint into an executable.

    Of the form the packaging inputs ask for, each the work of one packager.
    ``compiled`` is Nuitka's: it translates each module to C and compiles it,
    so the artifact holds native code and no bytecode of the application's,
    which is what a build handed to somebody who is not to read it needs and
    what makes it slow. ``bundled`` is PyInstaller's: the interpreter and the
    application's bytecode put together, which unpacks and decompiles back
    into source and is quick to make, for a build that stays among the
    people holding the source already.

    Either way the artifact is a directory, ``<dist_path>/<name>``, holding
    the executable under the same name -- ``<name>.exe`` on Windows and
    ``<name>.bin`` elsewhere -- so nothing that finds the executable in an
    artifact has to know which packager made it. A bundle holds everything
    the executable runs beside, at the same paths. A compile holds the one
    file and nothing else (the owner's ruling of 2026-10-18): Nuitka lays the
    same directory out, runs the signing command the inputs name on it, and
    packs it into the executable, which unpacks it on its first start under
    the user's cache directory, in a directory named for the application and
    for this build, and on every start after checks what is there rather
    than unpacking it again. The build's name in that path is made here, once
    per build, so two builds of one application never unpack over each other.

    Each packager keeps its intermediates beside its output, so it is
    pointed at ``work/`` under the scratch path it is given and the directory
    it builds there is moved out (`_driver`). What it is told about the
    application is a file -- a plugin for the compiler (`_application`), a
    spec for the bundler (`_spec`) -- and both files are written here, before
    the command that reads them is returned: they are this build's
    intermediates, in the directory the build was given for them. The
    command is then an interpreter and the driver.
    """
    name = _build_name(artifact_name=artifact_name)
    executable = name + (
        _EXECUTABLE_SUFFIX if os.name == _WINDOWS else _POSIX_EXECUTABLE_SUFFIX
    )
    named, unlocated = _loaded_by_name(
        entrypoint=entrypoint,
        packaging=packaging,
        test_directories=test_directories,
    )
    work = (scratch_path / "work").resolve()
    searched = [str(root.resolve()) for root in packaging.obtainedPackageRoots]
    artifact = dist_path.resolve() / name
    if packaging.form == _COMPILED:
        generated = (scratch_path / "nuitka").resolve()
        generated.mkdir(parents=True, exist_ok=True)
        entry_path = _standalone_entry(entrypoint=entrypoint, generated=generated)
        application_path = generated / "application.py"
        application_path.write_text(
            _application(named=named, packaging=packaging), encoding="utf-8"
        )
        packager = _COMPILER
        unpacked = "/".join(
            [_UNPACKED_UNDER, f"{name}{_UNPACKED_SUFFIX}", os.urandom(8).hex()]
        )
        driver = _driver(
            compiler=[
                "-m",
                "nuitka",
                "--onefile",
                f"--onefile-tempdir-spec={unpacked}",
                # The C compiler is Nuitka's to obtain where the machine has
                # none, and a build has nobody to ask.
                "--assume-yes-for-downloads",
                f"--output-dir={work}",
                f"--output-filename={executable}",
                f"--report={generated / 'report.xml'}",
                f"--user-plugin={application_path}",
                *(f"--include-package={package}" for package in unlocated),
                str(entry_path),
            ],
            searched=searched,
            built=work / executable,
            artifact=artifact,
            placed=artifact / executable,
        )
    else:
        generated = (scratch_path / "pyinstaller").resolve()
        generated.mkdir(parents=True, exist_ok=True)
        entry_path = _standalone_entry(entrypoint=entrypoint, generated=generated)
        spec_path = generated / f"{name}.spec"
        # What the packager brought with it. PyInstaller depends on
        # setuptools, so setuptools is in every environment it analyses, and
        # its own runtime hook then freezes it into an application that never
        # imports it. That is a fact about this packager rather than about the
        # application, so it is answered here -- and only where the
        # repository declares no setuptools of its own, since one that does
        # means it. Nuitka is told nothing of it: what it compiles is what
        # the application imports.
        packager_owned = (
            []
            if declares_requirement(
                directory=entrypoint.resolve().parent, name=_PACKAGER_DISTRIBUTION
            )
            else list(_PACKAGER_MODULES)
        )
        spec_path.write_text(
            _spec(
                entry_path=entry_path,
                executable=executable,
                name=name,
                named=named,
                unlocated=[
                    package for package in unlocated if package not in packager_owned
                ],
                packaging=packaging,
                packager_owned=packager_owned,
            ),
            encoding="utf-8",
        )
        packager = _BUNDLER
        driver = _driver(
            compiler=[
                "-m",
                "PyInstaller",
                "--noconfirm",
                "--clean",
                f"--distpath={work / 'dist'}",
                f"--workpath={work / 'build'}",
                str(spec_path),
            ],
            searched=searched,
            built=work / "dist" / name,
            artifact=artifact,
        )
    driver_path = generated / "build.py"
    driver_path.write_text(driver, encoding="utf-8")

    return Command(
        executable="uv",
        args=[
            "run",
            # An application is built from what it needs to run, not from
            # what its repository is developed with. Either packager takes
            # whatever an import anywhere in the graph can resolve, a
            # third-party package's optional import of a test runner
            # included, so the development group is left out of the
            # environment it reads. And the environment is one made for this
            # run: the repository's own keeps whatever an earlier run
            # installed into it, development group and all, and leaving the
            # group out of a sync removes nothing already there.
            "--isolated",
            "--no-dev",
            "--with",
            packager,
            "python",
            str(driver_path),
        ],
    )
