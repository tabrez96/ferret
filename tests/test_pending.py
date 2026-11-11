import stat

import pytest

from ferret import keys
from ferret.pending import (
    PENDING_TTL_SECONDS,
    delete_pending,
    is_expired,
    pending_path,
    read_pending,
    write_pending,
)

UID = "a" * 32


def test_roundtrip_and_encrypted_on_disk(tmp_path, dek):
    data = b"%PDF-1.7 secret statement bytes"
    path = write_pending(tmp_path, UID, 7, dek, data)
    assert path == tmp_path / UID / "7.pdf.enc"
    assert read_pending(tmp_path, UID, 7, dek) == data
    assert data not in path.read_bytes()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert [p.name for p in path.parent.iterdir()] == ["7.pdf.enc"]


def test_wrong_dek_or_other_statement_id_fails(tmp_path, dek):
    path = write_pending(tmp_path, UID, 7, dek, b"data")
    with pytest.raises(keys.DecryptionError):
        read_pending(tmp_path, UID, 7, keys.new_dek())
    path.rename(path.with_name("8.pdf.enc"))
    with pytest.raises(keys.DecryptionError):
        read_pending(tmp_path, UID, 8, dek)


def test_invalid_user_id_rejected(tmp_path):
    with pytest.raises(ValueError):
        pending_path(tmp_path, "../x", 1)


def test_delete_missing_ok(tmp_path, dek):
    delete_pending(tmp_path, UID, 1)
    write_pending(tmp_path, UID, 1, dek, b"x")
    delete_pending(tmp_path, UID, 1)
    assert not pending_path(tmp_path, UID, 1).exists()


def test_is_expired_boundary():
    assert not is_expired(1000, 1000 + 6 * 24 * 3600)
    assert not is_expired(1000, 1000 + PENDING_TTL_SECONDS - 1)
    assert is_expired(1000, 1000 + PENDING_TTL_SECONDS)
