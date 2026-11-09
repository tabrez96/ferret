"""Schema migrations shared by control.db and the user databases."""

from collections.abc import Sequence


def migrate(conn, migrations: Sequence[str]) -> int:
    """Apply migrations[user_version:] in order. Returns the final version."""
    current = conn.execute("PRAGMA user_version").fetchone()[0]
    if current > len(migrations):
        raise RuntimeError(
            f"database schema version {current} is newer than this code ({len(migrations)})"
        )
    for version, script in enumerate(migrations[current:], start=current + 1):
        try:
            conn.executescript(f"BEGIN;\n{script}\nPRAGMA user_version = {version};\nCOMMIT;")
        except Exception:
            if conn.in_transaction:
                conn.rollback()
            raise
    return len(migrations)
