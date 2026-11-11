"""Statement files waiting to be read, encrypted with the user's data key."""

import os
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from ferret.keys import NONCE_BYTES, DecryptionError, pending_key
from ferret.userdb import USER_ID_RE

PENDING_TTL_SECONDS = 7 * 24 * 60 * 60


def _aad(user_id: str, statement_id: int) -> bytes:
    return f"ferret/pending/v1:{user_id}:{statement_id}".encode()


def pending_path(pending_dir: Path, user_id: str, statement_id: int) -> Path:
    if not USER_ID_RE.fullmatch(user_id):
        raise ValueError("invalid user id")
    return pending_dir / user_id / f"{statement_id}.pdf.enc"


def write_pending(
    pending_dir: Path, user_id: str, statement_id: int, dek: bytes, data: bytes
) -> Path:
    path = pending_path(pending_dir, user_id, statement_id)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    nonce = os.urandom(NONCE_BYTES)
    body = nonce + AESGCM(pending_key(dek)).encrypt(nonce, data, _aad(user_id, statement_id))
    tmp = path.with_name(f"{path.name}.{os.urandom(8).hex()}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(body)
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return path


def read_pending(pending_dir: Path, user_id: str, statement_id: int, dek: bytes) -> bytes:
    body = pending_path(pending_dir, user_id, statement_id).read_bytes()
    nonce, ciphertext = body[:NONCE_BYTES], body[NONCE_BYTES:]
    try:
        return AESGCM(pending_key(dek)).decrypt(nonce, ciphertext, _aad(user_id, statement_id))
    except InvalidTag, ValueError:
        raise DecryptionError("cannot decrypt pending file") from None


def delete_pending(pending_dir: Path, user_id: str, statement_id: int) -> None:
    pending_path(pending_dir, user_id, statement_id).unlink(missing_ok=True)


def pending_deadline(received_at: int) -> int:
    return received_at + PENDING_TTL_SECONDS


def is_expired(received_at: int, now: int) -> bool:
    return now >= pending_deadline(received_at)
