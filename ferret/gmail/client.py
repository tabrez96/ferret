"""The Gmail interface the poll job uses."""

from collections.abc import Callable
from typing import Protocol


class GmailError(Exception):
    """A Gmail call failed; the next poll tries again."""


class GmailRevoked(GmailError):
    """Google rejected the refresh token (revoked or expired)."""


class GmailApi(Protocol):
    def search(self, query: str) -> list[str]:
        """Message ids, newest first."""
        ...

    def pdf_attachments(self, message_id: str) -> list[bytes]: ...


GmailFactory = Callable[[str], GmailApi]  # refresh token -> client
