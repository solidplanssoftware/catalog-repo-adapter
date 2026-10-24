"""The python adapter these tests are run against.

An adapter is a language core and a configuration document, so what a test
here asserts about the adapter is asserted about the two this repository
publishes, put together the way a resolver puts them together: the core this
package is, configured by `adapter/packages/repo_adapter/adapter.yml`.
"""

from __future__ import annotations

from pathlib import Path

from repo_adapter_api import configure_adapter, load_adapter_configuration

from repo_adapter import core

#: The document this repository publishes as `language:python`.
ADAPTER_DOCUMENT = (
    Path(__file__).resolve().parents[3]
    / "adapter"
    / "packages"
    / "repo_adapter"
    / "adapter.yml"
)

configuration = load_adapter_configuration(path=ADAPTER_DOCUMENT)
adapter = configure_adapter(core=core, configuration=configuration)
