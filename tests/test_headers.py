import re
from pathlib import Path

from ferret.web.headers import CSP, SECURITY_HEADERS

TEMPLATES = Path(__file__).parents[1] / "ferret" / "web" / "templates"


def test_every_header_on_page(client):
    response = client.get("/signin")
    for name, value in SECURITY_HEADERS.items():
        assert response.headers[name] == value


def test_headers_on_static_and_errors(client):
    for path in ("/static/css/ferret.css", "/no-such-page"):
        response = client.get(path)
        assert response.headers["Content-Security-Policy"] == CSP
        assert "max-age" in response.headers["Strict-Transport-Security"]


def test_csp_has_no_unsafe():
    assert "unsafe-inline" not in CSP
    assert "unsafe-eval" not in CSP


def test_templates_have_no_inline_script():
    files = list(TEMPLATES.rglob("*.html"))
    assert files
    for path in files:
        text = path.read_text()
        for tag in re.findall(r"<script\b[^>]*>", text):
            assert "src=" in tag, f"{path.name}: inline script"
        assert not re.search(r"\son[a-z]+\s*=", text), f"{path.name}: event handler attribute"
        assert not re.search(r"\sstyle\s*=", text), f"{path.name}: style attribute"
        assert "<style" not in text, f"{path.name}: style tag"
        assert "javascript:" not in text, f"{path.name}: javascript: url"
