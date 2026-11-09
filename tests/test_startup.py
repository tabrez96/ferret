import pytest
from fastapi.testclient import TestClient

from ferret.keys import MasterKeyError
from ferret.web.app import create_app


@pytest.fixture(autouse=True)
def _restore_root_logging():
    import logging

    root = logging.getLogger()
    handlers, level = list(root.handlers), root.level
    yield
    root.handlers[:] = handlers
    root.setLevel(level)


def test_refuses_to_start_without_key(monkeypatch, data_dir):
    monkeypatch.delenv("FERRET_MASTER_KEY_FILE", raising=False)
    monkeypatch.setenv("FERRET_DATA_DIR", str(data_dir))
    with pytest.raises(MasterKeyError), TestClient(create_app()):
        pass


def test_refuses_to_start_with_unreadable_key(monkeypatch, tmp_path, data_dir):
    monkeypatch.setenv("FERRET_MASTER_KEY_FILE", str(tmp_path / "missing.key"))
    monkeypatch.setenv("FERRET_DATA_DIR", str(data_dir))
    with pytest.raises(MasterKeyError), TestClient(create_app()):
        pass


def test_refuses_key_inside_data_dir(monkeypatch, data_dir):
    data_dir.mkdir()
    key = data_dir / "master.key"
    key.write_text("ab" * 32)
    monkeypatch.setenv("FERRET_MASTER_KEY_FILE", str(key))
    monkeypatch.setenv("FERRET_DATA_DIR", str(data_dir))
    with pytest.raises(MasterKeyError), TestClient(create_app()):
        pass


def test_starts_with_key_and_creates_control_db(monkeypatch, master_key_file, data_dir):
    monkeypatch.setenv("FERRET_MASTER_KEY_FILE", str(master_key_file))
    monkeypatch.setenv("FERRET_DATA_DIR", str(data_dir))
    app = create_app()
    with TestClient(app) as client:
        assert client.get("/healthz").status_code == 200
        assert len(app.state.kek) == 32
    assert (data_dir / "control.db").exists()
    assert (data_dir / "users").is_dir()
