from pathlib import Path

WEB = Path(__file__).resolve().parent.parent / "ferret" / "web"
TEMPLATES = sorted((WEB / "templates").iterdir())

# htmx 2 attributes that htmx 4 removed or renamed (hx-disable changed meaning: see the templates).
REMOVED_ATTRIBUTES = [
    "hx-disabled-elt",
    "hx-vars",
    "hx-params",
    "hx-prompt",
    "hx-ext",
    "hx-disinherit",
    "hx-inherit",
    "hx-request",
    "hx-history",
]


def test_statements_js_uses_htmx4_events():
    script = (WEB / "static" / "js" / "statements.js").read_text()
    for old in ("htmx:afterSettle", "htmx:beforeRequest", "detail.elt"):
        assert old not in script
    assert "htmx:after:settle" in script
    assert "htmx:before:request" in script


def test_templates_use_no_removed_attributes():
    for template in TEMPLATES:
        text = template.read_text()
        for attribute in REMOVED_ATTRIBUTES:
            assert f"{attribute}=" not in text, f"{template.name} uses {attribute}"


def test_no_cdn():
    assert 'src="/static/js/htmx.min.js"' in (WEB / "templates" / "base.html").read_text()
    for template in TEMPLATES:
        text = template.read_text()
        for host in ("unpkg.com", "jsdelivr", "cdnjs"):
            assert host not in text, f"{template.name} loads from {host}"
