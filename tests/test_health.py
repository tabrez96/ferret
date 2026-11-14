from fastapi.testclient import TestClient

from ferret.web.app import create_app

client = TestClient(create_app())


def test_healthz_returns_ok():
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_css_served():
    response = client.get("/static/css/ferret.css")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/css")


HTMX_VERSION = "4.0.1"


def test_htmx_vendored():
    response = client.get("/static/js/htmx.min.js")
    assert response.status_code == 200
    assert "htmx" in response.text
    assert HTMX_VERSION in response.text
    assert "2.0.4" not in response.text


def test_unknown_static_is_404():
    assert client.get("/static/css/missing.css").status_code == 404
