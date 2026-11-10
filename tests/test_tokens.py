import base64
import hashlib

from ferret.auth.tokens import hash_token, new_token


def test_new_token_is_32_random_bytes():
    t = new_token()
    assert len(base64.urlsafe_b64decode(t + "=")) == 32
    assert new_token() != t


def test_hash_token_is_sha256():
    t = new_token()
    assert hash_token(t) == hashlib.sha256(t.encode()).digest()
