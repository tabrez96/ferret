"""Search Gmail for statements and hand new PDFs to the pipeline."""

import logging
from collections.abc import Sequence

from ferret.gmail.client import GmailFactory, GmailRevoked
from ferret.keys import FIELD_GMAIL_REFRESH_TOKEN, decrypt_field
from ferret.parsers import PARSERS, Parser
from ferret.pipeline import submit_statement

logger = logging.getLogger(__name__)

POLL_INTERVAL_SECONDS = 6 * 60 * 60
FIRST_LOOKBACK_SECONDS = 90 * 24 * 60 * 60  # first check after connecting
OVERLAP_SECONDS = 24 * 60 * 60  # late-indexed mail; gmail_seen removes repeats


def gmail_connected(user_db) -> bool:
    row = user_db.execute("SELECT status FROM gmail_account WHERE id = 1").fetchone()
    return row is not None and row["status"] == "connected"


def search_since(row) -> int:
    if row["last_checked_at"] is None:
        return row["connected_at"] - FIRST_LOOKBACK_SECONDS
    return row["last_checked_at"] - OVERLAP_SECONDS


def poll_gmail(
    control_conn,
    user_db,
    dek: bytes,
    pending_dir,
    user_id: str,
    *,
    gmail_factory: GmailFactory,
    now: int,
    parsers: Sequence[Parser] = PARSERS,
) -> int:
    """Fetch new statement PDFs from Gmail. Returns the number of statements submitted."""
    row = user_db.execute("SELECT * FROM gmail_account WHERE id = 1").fetchone()
    if row is None or row["status"] != "connected":
        return 0
    token = decrypt_field(
        dek, row["refresh_token_ciphertext"], row["nonce"], field=FIELD_GMAIL_REFRESH_TOKEN
    )
    api = gmail_factory(token)
    since = search_since(row)
    submitted = 0
    try:
        for query in dict.fromkeys(p.gmail_query for p in parsers):
            for message_id in api.search(f"{query} after:{since}"):
                seen = user_db.execute(
                    "SELECT 1 FROM gmail_seen WHERE message_id = ?", (message_id,)
                ).fetchone()
                if seen:
                    continue
                for data in api.pdf_attachments(message_id):
                    submit_statement(
                        control_conn,
                        user_db,
                        dek,
                        pending_dir,
                        user_id,
                        data,
                        source="gmail",
                        source_ref=message_id,
                        now=now,
                    )
                    submitted += 1
                # Submit first, mark seen after: a crash in between refetches the message and
                # fingerprint dedupe drops the copy, where the other order could lose a statement.
                with user_db:
                    user_db.execute(
                        "INSERT INTO gmail_seen (message_id, seen_at) VALUES (?, ?)",
                        (message_id, now),
                    )
    except GmailRevoked:
        with user_db:
            user_db.execute("UPDATE gmail_account SET status = 'stopped' WHERE id = 1")
        logger.info("gmail: access revoked, stopped")
        return submitted
    with user_db:
        user_db.execute("UPDATE gmail_account SET last_checked_at = ? WHERE id = 1", (now,))
    logger.info("gmail: %d statements submitted", submitted)
    return submitted
