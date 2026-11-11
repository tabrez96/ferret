"""Thin layer over pikepdf (unlocking) and pdfplumber (text)."""

import io
from collections.abc import Iterator, Sequence
from contextlib import contextmanager

import pdfplumber
import pikepdf


class NotAPdf(Exception):
    """The bytes are not a readable PDF."""


class PasswordRequired(Exception):
    """The PDF is encrypted and none of the candidate passwords opened it."""


def _decrypted(data: bytes, password: str | None) -> bytes:
    with pikepdf.open(io.BytesIO(data), password=password or "") as pdf:
        out = io.BytesIO()
        pdf.save(out)
        return out.getvalue()


def unlock(data: bytes, passwords: Sequence[str]) -> tuple[bytes, int | None]:
    """Return (decrypted PDF bytes, index of the password used, or None if none was needed)."""
    try:
        return _decrypted(data, None), None
    except pikepdf.PasswordError:
        pass
    except pikepdf.PdfError:
        raise NotAPdf("not a readable PDF") from None
    for index, password in enumerate(passwords):
        try:
            return _decrypted(data, password), index
        except pikepdf.PasswordError:
            continue
        except pikepdf.PdfError:
            raise NotAPdf("not a readable PDF") from None
    raise PasswordRequired("no working password")


@contextmanager
def open_pdf(unlocked: bytes) -> Iterator[pdfplumber.PDF]:
    try:
        pdf = pdfplumber.open(io.BytesIO(unlocked))
    except Exception:
        raise NotAPdf("not a readable PDF") from None
    try:
        yield pdf
    finally:
        pdf.close()


def first_page_text(pdf: pdfplumber.PDF) -> str:
    try:
        if not pdf.pages:
            return ""
        return pdf.pages[0].extract_text() or ""
    except Exception:
        raise NotAPdf("not a readable PDF") from None
