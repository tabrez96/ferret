from ferret import control
from ferret.auth.sessions import (
    SESSION_TTL_SECONDS,
    SessionUser,
    create_session,
    delete_session,
    get_session_user,
)
from ferret.auth.tokens import hash_token

NOW = 1_800_000_000


def make_user(conn, kek):
    user_id, _ = control.create_user(conn, kek, "a@example.com", now=NOW)
    return user_id


def test_create_and_lookup(conn, kek):
    user_id = make_user(conn, kek)
    token = create_session(conn, user_id, now=NOW)
    assert get_session_user(conn, token, now=NOW + 1) == SessionUser(
        user_id, "a@example.com", "email"
    )
    assert get_session_user(conn, None, now=NOW) is None
    assert get_session_user(conn, "x" * 500, now=NOW) is None
    assert get_session_user(conn, "unknown", now=NOW) is None


def test_expired_session_is_none(conn, kek):
    token = create_session(conn, make_user(conn, kek), now=NOW)
    assert get_session_user(conn, token, now=NOW + SESSION_TTL_SECONDS - 1) is not None
    assert get_session_user(conn, token, now=NOW + SESSION_TTL_SECONDS) is None


def test_expired_sessions_are_tidied(conn, kek):
    user_id = make_user(conn, kek)
    create_session(conn, user_id, now=NOW)
    create_session(conn, user_id, now=NOW + SESSION_TTL_SECONDS)
    assert conn.execute("SELECT count(*) FROM sessions").fetchone()[0] == 1


def test_delete_session(conn, kek):
    token = create_session(conn, make_user(conn, kek), now=NOW)
    delete_session(conn, token)
    delete_session(conn, None)
    delete_session(conn, "x" * 500)
    assert get_session_user(conn, token, now=NOW) is None


def test_only_session_hash_stored(conn, kek, data_dir):
    token = create_session(conn, make_user(conn, kek), now=NOW)
    row = conn.execute("SELECT id_hash FROM sessions").fetchone()
    assert row["id_hash"] == hash_token(token)
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    assert token.encode() not in (data_dir / "control.db").read_bytes()


def test_method_defaults_to_email(conn, kek):
    user_id = make_user(conn, kek)
    create_session(conn, user_id, now=NOW)
    assert conn.execute("SELECT method FROM sessions").fetchone()["method"] == "email"
    token = create_session(conn, user_id, now=NOW, method="google")
    assert get_session_user(conn, token, now=NOW).method == "google"
