import logging
import smtplib

import pytest

from ferret.auth import mail
from ferret.auth.mail import (
    ConsoleMailer,
    MailError,
    SmtpMailer,
    UnconfiguredMailer,
    mailer_from_settings,
    signin_email,
)
from ferret.config import Settings


def settings(**kw) -> Settings:
    base = {"data_dir": "d", "master_key_file": None, "smtp_host": "smtp.test"}
    return Settings(**{**base, **kw})


class FakeSmtp:
    instances: list[FakeSmtp] = []
    fail_connect = False

    def __init__(self, host, port, timeout=None, context=None):
        if FakeSmtp.fail_connect:
            raise OSError("down")
        self.args = (host, port, timeout, context)
        self.calls: list[tuple] = []
        FakeSmtp.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def starttls(self, context=None):
        self.calls.append(("starttls",))

    def login(self, user, password):
        self.calls.append(("login", user, password))

    def send_message(self, msg):
        self.calls.append(("send", msg))


@pytest.fixture(autouse=True)
def fake_smtp(monkeypatch):
    FakeSmtp.instances = []
    FakeSmtp.fail_connect = False
    monkeypatch.setattr(smtplib, "SMTP", FakeSmtp)
    monkeypatch.setattr(smtplib, "SMTP_SSL", type("FakeSmtpSsl", (FakeSmtp,), {}))


def test_smtp_mailer_starttls_and_login():
    s = settings(smtp_username="u", smtp_password="p", smtp_from="Ferret <f@x.test>")
    SmtpMailer(s).send("a@example.com", "Subj", "Body")
    (smtp,) = FakeSmtp.instances
    assert type(smtp) is FakeSmtp
    assert smtp.args[:3] == ("smtp.test", 587, 10)
    assert [c[0] for c in smtp.calls] == ["starttls", "login", "send"]
    assert smtp.calls[1] == ("login", "u", "p")
    msg = smtp.calls[2][1]
    assert (msg["From"], msg["To"], msg["Subject"]) == (
        "Ferret <f@x.test>",
        "a@example.com",
        "Subj",
    )


def test_smtp_mailer_none_security_skips_tls_and_login():
    SmtpMailer(settings(smtp_security="none")).send("a@example.com", "S", "B")
    assert [c[0] for c in FakeSmtp.instances[0].calls] == ["send"]


def test_smtp_mailer_ssl_mode():
    SmtpMailer(settings(smtp_security="ssl", smtp_port=465)).send("a@example.com", "S", "B")
    (smtp,) = FakeSmtp.instances
    assert type(smtp).__name__ == "FakeSmtpSsl"
    assert "starttls" not in [c[0] for c in smtp.calls]


def test_smtp_errors_become_mail_error():
    FakeSmtp.fail_connect = True
    with pytest.raises(MailError):
        SmtpMailer(settings()).send("a@example.com", "S", "B")


def test_smtp_exception_becomes_mail_error(monkeypatch):
    def boom(self, msg):
        raise smtplib.SMTPRecipientsRefused({})

    monkeypatch.setattr(FakeSmtp, "send_message", boom)
    with pytest.raises(MailError):
        SmtpMailer(settings()).send("a@example.com", "S", "B")


def test_mailer_from_settings(caplog):
    assert isinstance(mailer_from_settings(settings(dev_print_links=True)), ConsoleMailer)
    assert isinstance(mailer_from_settings(settings()), SmtpMailer)
    with caplog.at_level(logging.WARNING, logger=mail.__name__):
        unconfigured = mailer_from_settings(settings(smtp_host=None))
    assert isinstance(unconfigured, UnconfiguredMailer)
    assert "SMTP is not configured" in caplog.text
    with pytest.raises(MailError):
        unconfigured.send("a@example.com", "S", "B")


def test_console_mailer_prints_body(capsys):
    ConsoleMailer().send("a@example.com", "S", "the link")
    assert "the link" in capsys.readouterr().err


def test_signin_email_contains_link_and_expiry():
    subject, body = signin_email("https://ferret.test/signin/link?token=abc")
    assert "sign-in" in subject
    assert "https://ferret.test/signin/link?token=abc" in body
    assert "15 minutes" in body
