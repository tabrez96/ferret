from fastapi.routing import APIRoute

from tests.conftest import csrf_token


def api_routes(routes):
    """Flatten app.routes; FastAPI wraps included routers in a single entry."""
    for route in routes:
        inner = getattr(route, "original_router", None)
        if inner is not None:
            yield from api_routes(inner.routes)
        elif isinstance(route, APIRoute):
            yield route


def test_every_post_route_rejects_missing_token(client, app):
    routes = [r for r in api_routes(app.routes) if "POST" in r.methods]
    assert {r.path for r in routes} >= {"/signin/email", "/signout"}
    assert routes
    for route in routes:
        response = client.post(route.path, data={"email": "a@example.com"})
        assert response.status_code == 403, route.path


def test_wrong_token_rejected(client):
    csrf_token(client)
    r = client.post("/signin/email", data={"email": "a@example.com", "csrf_token": "wrong"})
    assert r.status_code == 403


def test_missing_cookie_rejected(client):
    token = csrf_token(client)
    client.cookies.clear()
    r = client.post("/signin/email", data={"email": "a@example.com", "csrf_token": token})
    assert r.status_code == 403


def test_header_token_accepted(client):
    token = csrf_token(client)
    r = client.post(
        "/signin/email", data={"email": "a@example.com"}, headers={"x-csrf-token": token}
    )
    assert r.status_code == 200


def test_csrf_cookie_flags(client):
    r = client.get("/signin")
    cookie = next(c for c in r.headers.get_list("set-cookie") if c.startswith("ferret_csrf="))
    for flag in ("HttpOnly", "Secure", "SameSite=lax"):
        assert flag in cookie


def test_oversized_csrf_cookie_is_replaced(client):
    client.cookies.set("ferret_csrf", "x" * 500)
    r = client.get("/signin")
    assert any(c.startswith("ferret_csrf=") for c in r.headers.get_list("set-cookie"))
