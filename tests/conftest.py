import os
from pathlib import Path

import pytest

from ferret import keys


@pytest.fixture
def kek() -> bytes:
    return os.urandom(32)


@pytest.fixture
def dek() -> bytes:
    return keys.new_dek()


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    return tmp_path / "data"


@pytest.fixture
def master_key_file(tmp_path: Path) -> Path:
    path = tmp_path / "secrets" / "master.key"
    path.parent.mkdir()
    path.write_text(os.urandom(32).hex() + "\n")
    return path
