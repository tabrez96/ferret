import pytest

from ferret.pipeline.pdf import (
    NotAPdf,
    PasswordRequired,
    first_page_text,
    open_pdf,
    unlock,
)
from tests.fixtures.pdfs import make_pdf


def test_unlock_plain_pdf():
    unlocked, used = unlock(make_pdf(["HELLO LINE"]), ["unused"])
    assert used is None
    with open_pdf(unlocked) as pdf:
        assert "HELLO LINE" in first_page_text(pdf)


def test_unlock_with_second_password():
    unlocked, used = unlock(make_pdf(["HELLO LINE"], password="right"), ["wrong", "right"])
    assert used == 1
    with open_pdf(unlocked) as pdf:
        assert "HELLO LINE" in first_page_text(pdf)


def test_wrong_passwords_raise_password_required():
    data = make_pdf(["x"], password="right")
    with pytest.raises(PasswordRequired):
        unlock(data, ["a", "b"])
    with pytest.raises(PasswordRequired):
        unlock(data, [])


def test_garbage_raises_not_a_pdf():
    with pytest.raises(NotAPdf):
        unlock(b"this is not a pdf", [])
    with pytest.raises(NotAPdf):
        with open_pdf(b"garbage"):
            pass


def test_zero_page_pdf_has_no_text():
    import io

    import pikepdf

    buf = io.BytesIO()
    pikepdf.new().save(buf)
    with open_pdf(buf.getvalue()) as pdf:
        assert first_page_text(pdf) == ""


def test_first_page_text_failure_is_not_a_pdf():
    class Broken:
        @property
        def pages(self):
            raise RuntimeError("bad")

    with pytest.raises(NotAPdf):
        first_page_text(Broken())
