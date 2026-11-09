import os

import pytest

from ferret import keys
from ferret.keys import DecryptionError, MasterKeyError

UID = "a" * 32


def test_load_master_key_reads_hex(tmp_path, data_dir):
    raw = os.urandom(32)
    path = tmp_path / "k"
    path.write_text(raw.hex() + "\n")
    assert keys.load_master_key(path, data_dir) == raw


def test_load_master_key_missing_env(data_dir):
    with pytest.raises(MasterKeyError):
        keys.load_master_key(None, data_dir)


def test_load_master_key_missing_file(tmp_path, data_dir):
    with pytest.raises(MasterKeyError, match="cannot read"):
        keys.load_master_key(tmp_path / "nope", data_dir)


def test_load_master_key_not_ascii(tmp_path, data_dir):
    path = tmp_path / "k"
    path.write_bytes(b"\xff\xfe" * 32)
    with pytest.raises(MasterKeyError, match="cannot read"):
        keys.load_master_key(path, data_dir)


@pytest.mark.parametrize(
    "content",
    ["", "a" * 63, "a" * 65, "zz" * 32, "not-a-key-hunter2"],
)
def test_load_master_key_bad_content(tmp_path, data_dir, content):
    path = tmp_path / "k"
    path.write_text(content)
    with pytest.raises(MasterKeyError) as exc:
        keys.load_master_key(path, data_dir)
    if content:
        assert content not in str(exc.value)


def test_load_master_key_inside_data_dir(data_dir):
    data_dir.mkdir()
    path = data_dir / "master.key"
    path.write_text("ab" * 32)
    with pytest.raises(MasterKeyError, match="data directory"):
        keys.load_master_key(path, data_dir)


def test_load_master_key_symlink_into_data_dir(tmp_path, data_dir):
    data_dir.mkdir()
    real = data_dir / "master.key"
    real.write_text("ab" * 32)
    link = tmp_path / "link.key"
    link.symlink_to(real)
    with pytest.raises(MasterKeyError, match="data directory"):
        keys.load_master_key(link, data_dir)


def test_wrap_unwrap_round_trip(kek, dek):
    wrapped = keys.wrap_dek(kek, dek, UID)
    assert len(wrapped) == 60
    assert keys.unwrap_dek(kek, wrapped, UID) == dek


def test_wrap_uses_fresh_nonce(kek, dek):
    assert keys.wrap_dek(kek, dek, UID) != keys.wrap_dek(kek, dek, UID)


def test_unwrap_with_other_kek_fails(kek, dek):
    wrapped = keys.wrap_dek(kek, dek, UID)
    with pytest.raises(DecryptionError):
        keys.unwrap_dek(os.urandom(32), wrapped, UID)


def test_unwrap_for_other_user_fails(kek, dek):
    wrapped = keys.wrap_dek(kek, dek, UID)
    with pytest.raises(DecryptionError):
        keys.unwrap_dek(kek, wrapped, "b" * 32)


def test_unwrap_tampered_fails(kek, dek):
    wrapped = bytearray(keys.wrap_dek(kek, dek, UID))
    wrapped[-1] ^= 1
    with pytest.raises(DecryptionError):
        keys.unwrap_dek(kek, bytes(wrapped), UID)


def test_unwrap_wrong_length_fails(kek):
    with pytest.raises(DecryptionError):
        keys.unwrap_dek(kek, b"short", UID)


def test_field_round_trip(dek):
    field = keys.FIELD_STATEMENT_PASSWORD
    ciphertext, nonce = keys.encrypt_field(dek, "s3cret-ü", field=field)
    assert keys.decrypt_field(dek, ciphertext, nonce, field=field) == "s3cret-ü"


def test_field_fresh_nonce_each_time(dek):
    results = [
        keys.encrypt_field(dek, "same", field=keys.FIELD_STATEMENT_PASSWORD) for _ in range(50)
    ]
    assert len({nonce for _, nonce in results}) == 50
    assert len({ciphertext for ciphertext, _ in results}) == 50
    assert all(len(nonce) == 12 for _, nonce in results)


def test_field_wrong_dek_fails(dek):
    ciphertext, nonce = keys.encrypt_field(dek, "x", field=keys.FIELD_STATEMENT_PASSWORD)
    with pytest.raises(DecryptionError):
        keys.decrypt_field(keys.new_dek(), ciphertext, nonce, field=keys.FIELD_STATEMENT_PASSWORD)


def test_field_wrong_field_name_fails(dek):
    ciphertext, nonce = keys.encrypt_field(dek, "x", field=keys.FIELD_STATEMENT_PASSWORD)
    with pytest.raises(DecryptionError):
        keys.decrypt_field(dek, ciphertext, nonce, field=keys.FIELD_GMAIL_REFRESH_TOKEN)


def test_subkeys_differ(dek):
    sql, field = keys.sqlcipher_key(dek), keys.field_key(dek)
    assert sql != field
    assert dek not in (sql, field)
