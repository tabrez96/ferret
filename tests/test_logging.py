import io
import logging

from ferret.logging import RedactingFormatter, redact, setup_logging


def test_redacts_key_value_secrets():
    out = redact("password=hunter2 token: abc")
    assert "hunter2" not in out
    assert "abc" not in out


def test_redacts_quoted_secret():
    assert "my pass" not in redact('password="my pass" ok')


def test_redacts_json_secrets():
    out = redact('{"password": "hunter2"}')
    assert "hunter2" not in out
    assert "password" in out
    out = redact("{'token': 'abc123'}")
    assert "abc123" not in out
    assert "token" in out


def test_redacts_bearer():
    out = redact("Authorization header Bearer abc.DEF-123")
    assert "abc.DEF" not in out


def test_redacts_email():
    assert redact("sent to jo@example.com now") == "sent to <email> now"


def test_redacts_card_number():
    assert "4111" not in redact("card 4111 1111 1111 1111 used")


def test_redacts_long_tokens():
    assert redact("x " + "ab12" * 16) == "x <redacted>"


def test_keeps_user_ids_and_counts():
    text = f"user={'a1' * 16} rows=12"
    assert redact(text) == text


def test_formatter_redacts_args_and_tracebacks():
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(RedactingFormatter("%(message)s"))
    logger = logging.getLogger("test_redaction")
    logger.propagate = False
    logger.addHandler(handler)
    try:
        logger.error("pw %s", "password=hunter2")
        try:
            raise ValueError("bad password=hunter2")
        except ValueError:
            logger.exception("failed")
    finally:
        logger.removeHandler(handler)
    assert "hunter2" not in stream.getvalue()
    assert "ValueError" in stream.getvalue()


def test_setup_logging_idempotent():
    root = logging.getLogger()
    saved_handlers, saved_level = list(root.handlers), root.level
    try:
        setup_logging()
        setup_logging("DEBUG")
        assert len([h for h in root.handlers if getattr(h, "_ferret", False)]) == 1
        assert root.level == logging.DEBUG
    finally:
        root.handlers[:] = saved_handlers
        root.setLevel(saved_level)
