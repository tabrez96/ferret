import importlib

import pytest

SUBPACKAGES = ["web", "auth", "userdb", "pipeline", "parsers", "gmail", "mcp"]


@pytest.mark.parametrize("name", SUBPACKAGES)
def test_subpackages_import(name):
    assert importlib.import_module(f"ferret.{name}")
