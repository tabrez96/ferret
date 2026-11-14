"""S01: sign in with an emailed link, and sign out."""

import hmac
import sqlite3

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse, Response

from ferret import control
from ferret.auth import links
from ferret.auth.google import GoogleError
from ferret.auth.mail import MailError, signin_email
from ferret.auth.sessions import (
    SESSION_TTL_SECONDS,
    SessionUser,
    create_session,
    delete_session,
)
from ferret.auth.tokens import new_token
from ferret.userdb import open_user_db
from ferret.web.security import (
    SESSION_COOKIE,
    clear_cookie,
    control_conn,
    current_user,
    now,
    set_cookie,
    verify_csrf,
)
from ferret.web.templating import templates

router = APIRouter()

GOOGLE_COOKIE = "ferret_google"
GOOGLE_COOKIE_SECONDS = 600
_MAX_GOOGLE_COOKIE = 300


def render(
    request: Request,
    state: str,
    *,
    email: str = "",
    error: str | None = None,
    notice: str | None = None,
    status: int = 200,
) -> Response:
    return templates.TemplateResponse(
        request,
        "signin.html",
        {
            "state": state,
            "email": email,
            "error": error,
            "notice": notice,
            "csrf_token": request.state.csrf_token,
        },
        status_code=status,
    )


@router.get("/signin")
def signin_page(
    request: Request, deleted: str = "", user: SessionUser | None = Depends(current_user)
) -> Response:
    if user is not None:
        return RedirectResponse("/", status_code=303)
    return render(request, "form", notice="account_deleted" if deleted == "1" else None)


@router.post("/signin/email", dependencies=[Depends(verify_csrf)])
def request_link(
    request: Request,
    email: str = Form(""),
    conn: sqlite3.Connection = Depends(control_conn),
) -> Response:
    normalized = links.normalize_email(email)
    if normalized is None:
        return render(
            request,
            "form",
            email=email.strip(),
            error="Enter your email address, like you@example.com.",
        )
    token = links.issue_link(conn, normalized, now=now(request))
    link = f"{request.app.state.settings.base_url}/signin/link?token={token}"
    subject, body = signin_email(link)
    try:
        request.app.state.mailer.send(normalized, subject, body)
    except MailError:
        return render(
            request,
            "form",
            email=normalized,
            error="We couldn't send the link. Try again in a minute.",
        )
    return render(request, "sent", email=normalized)


@router.get("/signin/link")
def use_link(
    request: Request, token: str = "", conn: sqlite3.Connection = Depends(control_conn)
) -> Response:
    result = links.consume_link(conn, token, now=now(request))
    if not result.ok:
        return render(request, "expired", email=result.email or "")
    assert result.email is not None
    user_id = _get_or_create_user(request, conn, result.email)
    delete_session(conn, request.cookies.get(SESSION_COOKIE))
    session = create_session(conn, user_id, now=now(request), method="email")
    response = RedirectResponse("/", status_code=303)
    set_cookie(response, SESSION_COOKIE, session, SESSION_TTL_SECONDS)
    return response


def _get_or_create_user(
    request: Request, conn: sqlite3.Connection, email: str, *, google_sub: str | None = None
) -> str:
    user = control.get_user_by_email(conn, email)
    if user is not None:
        return user["id"]
    state = request.app.state
    try:
        user_id, dek = control.create_user(
            conn, state.kek, email, now=now(request), google_sub=google_sub
        )
    except sqlite3.IntegrityError:
        # Two first sign-ins for the same email (or Google account) raced; the other one created it.
        user = control.get_user_by_email(conn, email) or (
            google_sub and control.get_user_by_google_sub(conn, google_sub)
        )
        assert user is not None
        return user["id"]
    open_user_db(state.settings.users_dir, user_id, dek).close()
    return user_id


def _redirect_uri(request: Request) -> str:
    return f"{request.app.state.settings.base_url}/signin/google/callback"


@router.get("/signin/google")
def start_google(request: Request, user: SessionUser | None = Depends(current_user)) -> Response:
    if user is not None:
        return RedirectResponse("/", status_code=303)
    google = request.app.state.google
    if google is None:
        return render(request, "form", notice="google_unavailable")
    state, verifier = new_token(), new_token()
    url = google.authorization_url(
        state=state, code_verifier=verifier, redirect_uri=_redirect_uri(request)
    )
    response = RedirectResponse(url, status_code=303)
    set_cookie(response, GOOGLE_COOKIE, f"{state}.{verifier}", GOOGLE_COOKIE_SECONDS)
    return response


def _read_google_cookie(request: Request) -> tuple[str, str] | None:
    value = request.cookies.get(GOOGLE_COOKIE)
    if not value or len(value) > _MAX_GOOGLE_COOKIE:
        return None
    parts = value.split(".")
    if len(parts) != 2:
        return None
    return parts[0], parts[1]


def _google_refused(request: Request, notice: str, *, email: str = "") -> Response:
    response = render(request, "form", email=email, notice=notice)
    clear_cookie(response, GOOGLE_COOKIE)
    return response


@router.get("/signin/google/callback")
def google_callback(
    request: Request,
    state: str = "",
    code: str = "",
    error: str = "",
    conn: sqlite3.Connection = Depends(control_conn),
) -> Response:
    google = request.app.state.google
    if google is None:
        return _google_refused(request, "google_unavailable")
    if error == "access_denied":
        response = RedirectResponse("/signin", status_code=303)
        clear_cookie(response, GOOGLE_COOKIE)
        return response
    cookie = _read_google_cookie(request)
    if (
        cookie is None
        or error
        or not code
        or not state
        or not hmac.compare_digest(state.encode(), cookie[0].encode())
    ):
        return _google_refused(request, "google_failed")
    try:
        identity = google.fetch_identity(
            code=code, code_verifier=cookie[1], redirect_uri=_redirect_uri(request)
        )
    except GoogleError:
        return _google_refused(request, "google_failed")
    email = links.normalize_email(identity.email or "")
    if email is None:
        return _google_refused(request, "google_failed")
    if not identity.email_verified:
        return _google_refused(request, "google_unverified", email=email)
    user_id = _google_account(request, conn, identity.sub, email)
    if user_id is None:
        return _google_refused(request, "google_failed")
    delete_session(conn, request.cookies.get(SESSION_COOKIE))
    session = create_session(conn, user_id, now=now(request), method="google")
    response = RedirectResponse("/", status_code=303)
    set_cookie(response, SESSION_COOKIE, session, SESSION_TTL_SECONDS)
    clear_cookie(response, GOOGLE_COOKIE)
    return response


def _google_account(request: Request, conn: sqlite3.Connection, sub: str, email: str) -> str | None:
    user = control.get_user_by_google_sub(conn, sub)
    if user is not None:
        return user["id"]  # already linked; the Google email may have changed since
    user_id = _get_or_create_user(request, conn, email, google_sub=sub)
    return user_id if control.link_google_sub(conn, user_id, sub) else None


@router.post("/signout", dependencies=[Depends(verify_csrf)])
def sign_out(request: Request, conn: sqlite3.Connection = Depends(control_conn)) -> Response:
    delete_session(conn, request.cookies.get(SESSION_COOKIE))
    response = RedirectResponse("/signin", status_code=303)
    clear_cookie(response, SESSION_COOKIE)
    return response
