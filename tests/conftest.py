import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

import pytest
from fastapi.testclient import TestClient

from ferret import control, keys
from ferret.auth.google import GOOGLE_SCOPES, GoogleError, GoogleIdentity
from ferret.auth.mail import MailError
from ferret.userdb import open_user_db
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


class FakeGoogle:
    def __init__(self) -> None:
        self.identity = GoogleIdentity("google-sub-1", "a@example.com", True)
        self.fail = False
        self.calls: list[dict] = []

    def authorization_url(self, *, state: str, code_verifier: str, redirect_uri: str) -> str:
        query = {"state": state, "redirect_uri": redirect_uri, "scope": GOOGLE_SCOPES}
        return "https://accounts.google.test/auth?" + urlencode(query)

    def fetch_identity(self, *, code: str, code_verifier: str, redirect_uri: str) -> GoogleIdentity:
        self.calls.append(
            {"code": code, "code_verifier": code_verifier, "redirect_uri": redirect_uri}
        )
        if self.fail:
            raise GoogleError("fake failure")
        return self.identity


@pytest.fixture
def google() -> FakeGoogle:
    return FakeGoogle()


@pytest.fixture
def mailer() -> FakeMailer:
    return FakeMailer()


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def app(monkeypatch, master_key_file, data_dir, clock, mailer, google):
    monkeypatch.setenv("FERRET_MASTER_KEY_FILE", str(master_key_file))
    monkeypatch.setenv("FERRET_DATA_DIR", str(data_dir))
    monkeypatch.setenv("FERRET_BASE_URL", "https://ferret.test")
    return create_app(clock=clock, mailer=mailer, google=google)


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


def google_sign_in(client: TestClient):
    start = client.get("/signin/google")
    state = parse_qs(urlparse(start.headers["location"]).query)["state"][0]
    return client.get("/signin/google/callback", params={"state": state, "code": "c"})


@dataclass
class UserEnv:
    user_id: str
    dek: bytes
    db: object
    users_dir: Path
    pending_dir: Path


@pytest.fixture
def user(conn, kek, data_dir, clock):
    user_id, user_dek = control.create_user(conn, kek, "u@example.com", now=clock())
    users_dir = data_dir / "users"
    db = open_user_db(users_dir, user_id, user_dek)
    yield UserEnv(user_id, user_dek, db, users_dir, data_dir / "pending")
    db.close()
