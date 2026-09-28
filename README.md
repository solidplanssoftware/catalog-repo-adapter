# The shared adapter catalog

Released versions of the repository adapters every project's tree resolves,
and nothing else. It is shared between projects, and a client keeps a fork of
it beside their fork of the adapters. A release is a version and the commit it
was cut from, and each entry states both.

## What is here

`repo-adapter/` holds each release as its source: `<category>/<name>/<version>/packages/<package>/`,
the tracked files of the adapter's module at the released commit, which the
resolver puts on the import path as they are. A release's pull request shows
the adapter's source as it will run.

The catalog states `indexLayout: per-package` in its `pkgmgr.manifest.yml`:
its index is one `.pkgmgr/pkgs/<namespace>/<name>.yml` per adapter, `latest`
worked out from the versions present, so two releases of different adapters
touch no common file. One version released twice with different source still
meets as an add/add conflict, which is write-once governance at the merge.

## How a release arrives

`ops project release` in an adapter's own repository publishes it here with
`--commit`: a branch named `release/<project>@<version>`, one commit naming the
release, the released commit (`Source:`) and the repository holding it
(`Repository:`), and a pull request against `master`. Nothing lands on
`master` except by that pull request, and merging it is what releases the
version: `ops project release --finish` then tags the adapter's repository at
the released commit.

## The merge check

`.github/workflows/verify.yml` runs `ops catalogs verify` on every pull
request. It refuses a release whose commit is not on its repository's default
branch -- a release branch not yet merged, or rewritten after it was
published -- so the catalog never releases a commit nobody can obtain from
where releases are obtained.

## Obtaining it

From a project's tree, with `CATALOG_ROOT` set to it, run `ops catalogs clone
--adapter --url <this repository> --path <an absolute path>`. It clones here
and records the clone in the tree's `repo-adapter` catalog as its pull-only
`public` store, brought up to date from `master` before every read and write.
