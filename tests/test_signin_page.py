import re

import pytest

from ferret.web.templating import templates


def render(state="form", **ctx) -> str:
    context = {
        "state": state,
        "email": "",
        "error": None,
        "notice": None,
        "csrf_token": "tok",
        **ctx,
    }
    return templates.env.get_template("signin.html").render(**context)


def test_main_state():
    html = render()
    assert "See what you spend on your cards. Type nothing." in html
    assert html.count('<span aria-hidden="true">✓</span>') == 4
    assert "Continue with Google" in html
    assert "Email me a sign-in link" in html
    assert "No Ferret password to remember." in html
    assert "New here?" in html
    assert '<input type="hidden" name="csrf_token" value="tok">' in html
    assert "/static/js/signin.js" in html
    assert "Sending…" in html


def test_sent_state():
    html = render("sent", email="a@example.com")
    assert "Check your inbox" in html
    assert "<strong>a@example.com</strong>" in html
    assert "Send another link" in html
    assert '<a class="text-button" href="/signin">Use a different email</a>' in html
    assert 'name="email" value="a@example.com"' in html


def test_expired_state():
    html = render("expired", email="a@example.com")
    assert "That sign-in link has expired." in html
    assert "New here?" not in html
    assert "Email me a new link" in html
    assert 'value="a@example.com"' in html


def test_error_is_announced():
    html = render(error="Oops")
    assert 'aria-describedby="email-error"' in html
    assert 'aria-invalid="true"' in html
    assert 'id="email-error" role="alert">Oops' in html


def test_email_is_escaped():
    assert "<script>" not in render("sent", email="<script>@x.y")


def test_no_remote_assets():
    for state in ("form", "sent", "expired"):
        assert not re.search(r'(src|href)="https?://', render(state))


@pytest.mark.parametrize(
    ("notice", "copy"),
    [
        ("google_failed", "We couldn't sign you in with Google."),
        ("google_unverified", "Google hasn't confirmed this email address."),
        ("google_unavailable", "Google sign-in isn't set up here."),
    ],
)
def test_google_notices(notice, copy):
    html = render(notice=notice)
    assert copy in html
    assert 'class="notice notice-danger" role="alert"' in html
    assert "Continue with Google" in html
    assert 'action="/signin/email"' in html


def test_no_notice_by_default():
    assert "notice-danger" not in render()
