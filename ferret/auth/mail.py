"""Sending the sign-in email."""

import logging
import smtplib
import ssl
import sys
from email.message import EmailMessage
from typing import Protocol

from ferret.config import Settings

log = logging.getLogger(__name__)


class MailError(Exception):
    """The sign-in email could not be sent."""


class Mailer(Protocol):
    def send(self, to: str, subject: str, body: str) -> None: ...


class SmtpMailer:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def send(self, to: str, subject: str, body: str) -> None:
        s = self._settings
        msg = EmailMessage()
        msg["From"] = s.smtp_from
        msg["To"] = to
        msg["Subject"] = subject
        msg.set_content(body)
        try:
            if s.smtp_security == "ssl":
                smtp = smtplib.SMTP_SSL(
                    s.smtp_host, s.smtp_port, timeout=10, context=ssl.create_default_context()
                )
            else:
                smtp = smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=10)
            with smtp:
                if s.smtp_security == "starttls":
                    smtp.starttls(context=ssl.create_default_context())
                if s.smtp_username:
                    smtp.login(s.smtp_username, s.smtp_password or "")
                smtp.send_message(msg)
        except smtplib.SMTPException, OSError:
            raise MailError("could not send email") from None


class ConsoleMailer:
    """FERRET_DEV_PRINT_LINKS=1: prints the email to stderr. Local development only."""

    def send(self, to: str, subject: str, body: str) -> None:
        # print, not logging: the log redactor would hide the link
        print(f"[ferret dev] sign-in email for {to}:\n{body}", file=sys.stderr, flush=True)


class UnconfiguredMailer:
    def send(self, to: str, subject: str, body: str) -> None:
        raise MailError("SMTP is not configured")


def mailer_from_settings(settings: Settings) -> Mailer:
    if settings.dev_print_links:
        return ConsoleMailer()
    if settings.smtp_host:
        return SmtpMailer(settings)
    log.warning("SMTP is not configured; sign-in emails will fail")
    return UnconfiguredMailer()


def signin_email(link: str) -> tuple[str, str]:
    subject = "Your Ferret sign-in link"
    body = (
        "Here is your link to sign in to Ferret:\n\n"
        f"{link}\n\n"
        "It works once and expires in 15 minutes. "
        "If you didn't ask for it, you can ignore this email.\n"
    )
    return subject, body
