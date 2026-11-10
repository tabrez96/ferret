from pathlib import Path

import pytest

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


def test_sign_in_defaults():
    s = Settings.from_env({})
    assert s.base_url == "http://127.0.0.1:8000"
    assert s.smtp_host is None and s.smtp_port == 587 and s.smtp_security == "starttls"
    assert s.smtp_from == "Ferret <no-reply@localhost>"
    assert not s.dev_print_links


def test_sign_in_env():
    s = Settings.from_env(
        {
            "FERRET_BASE_URL": "https://ferret.example/",
            "FERRET_SMTP_HOST": "smtp.example",
            "FERRET_SMTP_PORT": "465",
            "FERRET_SMTP_USERNAME": "u",
            "FERRET_SMTP_PASSWORD": "p",
            "FERRET_SMTP_FROM": "Me <me@example.com>",
            "FERRET_SMTP_SECURITY": "ssl",
            "FERRET_DEV_PRINT_LINKS": "1",
        }
    )
    assert s.base_url == "https://ferret.example"
    assert (s.smtp_host, s.smtp_port, s.smtp_username, s.smtp_password) == (
        "smtp.example",
        465,
        "u",
        "p",
    )
    assert s.smtp_from == "Me <me@example.com>" and s.smtp_security == "ssl"
    assert s.dev_print_links


def test_empty_sign_in_env_is_unset():
    env = {f"FERRET_SMTP_{n}": "" for n in ("HOST", "PORT", "FROM", "SECURITY", "USERNAME")}
    s = Settings.from_env({**env, "FERRET_BASE_URL": ""})
    assert s.smtp_host is None and s.smtp_port == 587 and s.smtp_security == "starttls"
    assert s.smtp_from == "Ferret <no-reply@localhost>"


def test_invalid_smtp_settings():
    with pytest.raises(ValueError, match="starttls, ssl or none"):
        Settings.from_env({"FERRET_SMTP_SECURITY": "tls"})
    with pytest.raises(ValueError, match="must be a number"):
        Settings.from_env({"FERRET_SMTP_PORT": "x"})
