"""A Gmail client for tests, and a helper that connects an account."""

from ferret.gmail.client import GmailRevoked
from ferret.keys import FIELD_GMAIL_REFRESH_TOKEN, encrypt_field


class FakeGmail:
    def __init__(self) -> None:
        self.messages: dict[str, list[bytes]] = {}
        self.queries: list[str] = []
        self.fetched: list[str] = []
        self.revoked = False
        self.error: Exception | None = None

    def search(self, query: str) -> list[str]:
        if self.revoked:
            raise GmailRevoked("revoked")
        if self.error is not None:
            raise self.error
        self.queries.append(query)
        return list(self.messages)

    def pdf_attachments(self, message_id: str) -> list[bytes]:
        self.fetched.append(message_id)
        return self.messages[message_id]


def connect_gmail(db, dek, token, *, now, last_checked_at=None, status="connected"):
    ciphertext, nonce = encrypt_field(dek, token, field=FIELD_GMAIL_REFRESH_TOKEN)
    with db:
        db.execute(
            "INSERT INTO gmail_account (id, email, refresh_token_ciphertext, nonce,"
            " connected_at, last_checked_at, status) VALUES (1, 'g@example.com', ?, ?, ?, ?, ?)",
            (ciphertext, nonce, now, last_checked_at, status),
        )
