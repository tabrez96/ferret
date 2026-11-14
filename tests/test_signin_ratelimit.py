from ferret.web.signin import LINK_LIMIT_WINDOW_SECONDS, LINKS_PER_EMAIL, LINKS_PER_IP
from tests.conftest import csrf_token


def request_link(client, email):
    return client.post(
        "/signin/email", data={"email": email}, headers={"x-csrf-token": csrf_token(client)}
    )


def test_sixth_link_for_same_email_is_refused(client, mailer):
    for _ in range(LINKS_PER_EMAIL):
        assert request_link(client, "a@example.com").status_code == 200
    assert len(mailer.sent) == LINKS_PER_EMAIL
    response = request_link(client, "a@example.com")
    assert response.status_code == 429
    assert "Too many sign-in links were requested" in response.text
    assert len(mailer.sent) == LINKS_PER_EMAIL


def test_email_limit_resets_after_window(client, mailer, clock):
    for _ in range(LINKS_PER_EMAIL + 1):
        request_link(client, "a@example.com")
    clock.advance(LINK_LIMIT_WINDOW_SECONDS + 1)
    assert request_link(client, "a@example.com").status_code == 200
    assert len(mailer.sent) == LINKS_PER_EMAIL + 1


def test_ip_limit_across_emails(client, mailer):
    for i in range(LINKS_PER_IP):
        assert request_link(client, f"u{i}@example.com").status_code == 200
    assert request_link(client, "late@example.com").status_code == 429
    assert len(mailer.sent) == LINKS_PER_IP


def test_blocked_ip_does_not_charge_email(client, mailer, clock):
    for i in range(LINKS_PER_IP):
        request_link(client, f"u{i}@example.com")
    for _ in range(LINKS_PER_EMAIL):
        assert request_link(client, "x@example.com").status_code == 429
    clock.advance(LINK_LIMIT_WINDOW_SECONDS + 1)
    sent = len(mailer.sent)
    for _ in range(LINKS_PER_EMAIL):
        assert request_link(client, "x@example.com").status_code == 200
    assert len(mailer.sent) == sent + LINKS_PER_EMAIL


def test_invalid_email_not_counted(client, mailer):
    for _ in range(LINKS_PER_IP + 5):
        assert request_link(client, "not-an-email").status_code == 200
    assert not mailer.sent
    assert request_link(client, "ok@example.com").status_code == 200
    assert len(mailer.sent) == 1


def test_refused_email_does_not_charge_ip(client, mailer):
    for _ in range(LINKS_PER_EMAIL):
        request_link(client, "a@example.com")
    for _ in range(LINKS_PER_IP):
        assert request_link(client, "a@example.com").status_code == 429
    # The IP bucket holds only the 5 sent links, so other users on this IP still get through.
    for i in range(LINKS_PER_IP - LINKS_PER_EMAIL):
        assert request_link(client, f"u{i}@example.com").status_code == 200
