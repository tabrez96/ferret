"""Master key, per-user data keys and secret-field encryption."""

import os
import re
import secrets
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

KEY_BYTES = 32
NONCE_BYTES = 12
FIELD_STATEMENT_PASSWORD = "statement_password"
FIELD_GMAIL_REFRESH_TOKEN = "gmail_refresh_token"

_HEX_KEY_RE = re.compile(r"[0-9a-fA-F]{64}")


class MasterKeyError(RuntimeError):
    """The master key is missing, unreadable, malformed or stored in the data directory."""


class DecryptionError(Exception):
    """Authenticated decryption failed (wrong key, wrong context or tampered data)."""


def load_master_key(key_file: Path | None, data_dir: Path) -> bytes:
    if key_file is None:
        raise MasterKeyError("FERRET_MASTER_KEY_FILE is not set")
    key_path = key_file.resolve()
    data_path = data_dir.resolve()
    if key_path.is_relative_to(data_path):
        raise MasterKeyError("master key file must not be inside the data directory")
    try:
        text = key_path.read_text(encoding="ascii").strip()
    except OSError, UnicodeDecodeError:
        raise MasterKeyError(f"cannot read master key file {key_file}") from None
    if not _HEX_KEY_RE.fullmatch(text):
        raise MasterKeyError("master key file must contain 64 hex characters (32 bytes)")
    return bytes.fromhex(text)


def new_dek() -> bytes:
    return secrets.token_bytes(KEY_BYTES)


def _dek_aad(user_id: str) -> bytes:
    return b"ferret/dek/v1:" + user_id.encode()


def wrap_dek(kek: bytes, dek: bytes, user_id: str) -> bytes:
    nonce = os.urandom(NONCE_BYTES)
    return nonce + AESGCM(kek).encrypt(nonce, dek, _dek_aad(user_id))


def unwrap_dek(kek: bytes, wrapped: bytes, user_id: str) -> bytes:
    nonce, ciphertext = wrapped[:NONCE_BYTES], wrapped[NONCE_BYTES:]
    try:
        return AESGCM(kek).decrypt(nonce, ciphertext, _dek_aad(user_id))
    except InvalidTag, ValueError:
        raise DecryptionError("cannot unwrap data key") from None


def _subkey(dek: bytes, info: bytes) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=info).derive(dek)


def sqlcipher_key(dek: bytes) -> bytes:
    return _subkey(dek, b"ferret/sqlcipher/v1")


def field_key(dek: bytes) -> bytes:
    return _subkey(dek, b"ferret/field/v1")


def pending_key(dek: bytes) -> bytes:
    return _subkey(dek, b"ferret/pending/v1")


def _field_aad(field: str) -> bytes:
    return b"ferret/field/v1:" + field.encode()


def encrypt_field(dek: bytes, plaintext: str, *, field: str) -> tuple[bytes, bytes]:
    """Return `(ciphertext, nonce)`."""
    nonce = os.urandom(NONCE_BYTES)
    ciphertext = AESGCM(field_key(dek)).encrypt(nonce, plaintext.encode(), _field_aad(field))
    return ciphertext, nonce


def decrypt_field(dek: bytes, ciphertext: bytes, nonce: bytes, *, field: str) -> str:
    try:
        return AESGCM(field_key(dek)).decrypt(nonce, ciphertext, _field_aad(field)).decode()
    except InvalidTag, ValueError:
        raise DecryptionError("cannot decrypt field") from None
