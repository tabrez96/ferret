import pytest

from ferret import control
from ferret.auth.sessions import create_session
from ferret.history import CHIPS
from ferret.userdb import open_user_db
from ferret.web.security import SESSION_COOKIE
from tests.test_history import add, ts


@pytest.fixture
def signed_in(client, app, conn, clock):
    user_id, dek = control.create_user(conn, app.state.kek, "p@example.com", now=clock())
    client.cookies.set(SESSION_COOKIE, create_session(conn, user_id, now=clock()))
    db = open_user_db(app.state.settings.users_dir, user_id, dek)
    yield db
    db.close()


def test_signed_out_redirects(client):
    response = client.get("/statements")
    assert response.status_code == 303
    assert response.headers["location"] == "/signin"


def test_empty_page(client, signed_in):
    html = client.get("/statements").text
    assert "No statements yet" in html
    assert "Drop a statement PDF here" in html
    assert "Ferret reads the file, checks the totals, then deletes it." in html
    assert "<table" not in html
    assert '<a href="/statements" aria-current="page">' in html
    assert (
        '<button type="button" class="btn btn-primary" data-pick-file>Choose PDF</button>' in html
    )
    assert 'accept=".pdf,application/pdf" multiple' in html
    assert "/static/js/statements.js" in html
    assert 'data-upload-url="/statements/upload"' in html
    assert 'id="upload-notices"' in html


def test_history_chips_have_words(client, signed_in):
    for status in CHIPS:
        add(signed_in, status)
    html = client.get("/statements").text
    for word, tone in CHIPS.values():
        assert f'<span class="chip chip-{tone}">{word}</span>' in html.replace("&#39;", "'")


def test_needs_password_row(client, signed_in):
    sid = add(signed_in, "needs_password", received_at=ts(2026, 10, 31))
    html = client.get("/statements").text
    assert "Waiting until 7 Nov" in html
    assert f'href="/statements/{sid}/password">Enter password</a>' in html


def test_row_text_is_escaped(client, signed_in):
    add(signed_in, bank="<b>x</b>")
    html = client.get("/statements").text
    assert "&lt;b&gt;x&lt;/b&gt;" in html
    assert "<b>x</b>" not in html
