import sqlite3

import pytest

from ferret.db import migrate

ONE = "CREATE TABLE a (x INTEGER);"
TWO = "CREATE TABLE b (x INTEGER);"


def tables(conn):
    return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}


def version(conn):
    return conn.execute("PRAGMA user_version").fetchone()[0]


def test_migrate_applies_in_order_and_sets_version():
    conn = sqlite3.connect(":memory:")
    assert migrate(conn, [ONE, TWO]) == 2
    assert version(conn) == 2
    assert tables(conn) == {"a", "b"}


def test_migrate_is_idempotent():
    conn = sqlite3.connect(":memory:")
    migrate(conn, [ONE, TWO])
    assert migrate(conn, [ONE, TWO]) == 2
    assert version(conn) == 2


def test_migrate_applies_only_new_scripts():
    conn = sqlite3.connect(":memory:")
    migrate(conn, [ONE])
    migrate(conn, [ONE, TWO])
    assert version(conn) == 2
    assert tables(conn) == {"a", "b"}


def test_migrate_rolls_back_failed_script():
    conn = sqlite3.connect(":memory:")
    with pytest.raises(sqlite3.Error):
        migrate(conn, [ONE, "CREATE TABLE c (x INTEGER); CREATE TABLE a (x INTEGER);"])
    assert version(conn) == 1
    assert tables(conn) == {"a"}


def test_migrate_rejects_newer_schema():
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA user_version = 5")
    with pytest.raises(RuntimeError, match="newer"):
        migrate(conn, [ONE])
