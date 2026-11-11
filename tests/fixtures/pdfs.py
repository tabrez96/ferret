"""Synthetic PDFs for tests."""

import io
from collections.abc import Sequence

import pikepdf
from reportlab.pdfgen import canvas


def make_pdf(lines: Sequence[str], password: str | None = None) -> bytes:
    buf = io.BytesIO()
    page = canvas.Canvas(buf)
    for i, line in enumerate(lines):
        page.drawString(72, 800 - 14 * i, line)
    page.save()
    return buf.getvalue() if password is None else encrypt_pdf(buf.getvalue(), password)


def encrypt_pdf(data: bytes, password: str) -> bytes:
    out = io.BytesIO()
    with pikepdf.open(io.BytesIO(data)) as pdf:
        pdf.save(out, encryption=pikepdf.Encryption(user=password, owner=password, R=6))
    return out.getvalue()
