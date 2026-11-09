from pathlib import Path

from ferret.config import Settings


def test_defaults():
    s = Settings.from_env({})
    assert s.data_dir == Path("data")
    assert s.master_key_file is None
    assert s.control_db_path == Path("data/control.db")
    assert s.users_dir == Path("data/users")


def test_whitespace_key_is_unset():
    assert Settings.from_env({"FERRET_MASTER_KEY_FILE": "  "}).master_key_file is None


def test_reads_env():
    s = Settings.from_env({"FERRET_DATA_DIR": "/d", "FERRET_MASTER_KEY_FILE": "/k"})
    assert s.data_dir == Path("/d") and s.master_key_file == Path("/k")
