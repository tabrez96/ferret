import logging
import os
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ferret import control, keys
from ferret.auth.mail import MailError
from ferret.web.app import create_app
from ferret.web.security import CSRF_COOKIE


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


@pytest.fixture(autouse=True)
def _restore_root_logging():
    root = logging.getLogger()
    handlers, level = list(root.handlers), root.level
    yield
    root.handlers[:] = handlers
    root.setLevel(level)


class FakeMailer:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str, str]] = []
        self.fail = False

    def send(self, to: str, subject: str, body: str) -> None:
        if self.fail:
            raise MailError("fake failure")
        self.sent.append((to, subject, body))


class FakeClock:
    def __init__(self) -> None:
        self.now = 1_800_000_000

    def __call__(self) -> int:
        return self.now

    def advance(self, seconds: int) -> None:
        self.now += seconds


@pytest.fixture
def mailer() -> FakeMailer:
    return FakeMailer()


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def app(monkeypatch, master_key_file, data_dir, clock, mailer):
    monkeypatch.setenv("FERRET_MASTER_KEY_FILE", str(master_key_file))
    monkeypatch.setenv("FERRET_DATA_DIR", str(data_dir))
    monkeypatch.setenv("FERRET_BASE_URL", "https://ferret.test")
    return create_app(clock=clock, mailer=mailer)


@pytest.fixture
def client(app):
    # https: httpx only sends Secure cookies over https.
    with TestClient(app, base_url="https://testserver", follow_redirects=False) as c:
        yield c


def csrf_token(client: TestClient) -> str:
    client.get("/signin")
    return client.cookies[CSRF_COOKIE]


def link_token(mailer: FakeMailer) -> str:
    match = re.search(r"token=([A-Za-z0-9_-]+)", mailer.sent[-1][2])
    assert match
    return match.group(1)


@pytest.fixture
def conn(data_dir):
    connection = control.connect(data_dir / "control.db")
    yield connection
    connection.close()
