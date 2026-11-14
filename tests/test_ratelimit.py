import pytest

from ferret import control, ratelimit


@pytest.fixture
def db(tmp_path):
    connection = control.connect(tmp_path / "control.db")
    yield connection
    connection.close()


def count(db, bucket="a"):
    return db.execute("SELECT count(*) FROM rate_events WHERE bucket = ?", (bucket,)).fetchone()[0]


def allow(db, now, bucket="a"):
    return ratelimit.allow(db, bucket, now=now, limit=3, window=60)


def test_allows_under_limit(db):
    assert [allow(db, 100) for _ in range(3)] == [True, True, True]
    assert count(db) == 3


def test_refuses_at_limit(db):
    for _ in range(3):
        allow(db, 100)
    assert allow(db, 100) is False
    assert count(db) == 3


def test_window_expiry(db):
    for _ in range(3):
        allow(db, 100)
    assert allow(db, 159) is False
    assert allow(db, 160) is True
    assert count(db) == 1


def test_buckets_independent(db):
    for _ in range(3):
        allow(db, 100)
    assert allow(db, 100, bucket="b") is True
