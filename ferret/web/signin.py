"""S01: sign in with an emailed link, and sign out."""

import sqlite3

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse, Response

from ferret import control
from ferret.auth import links
from ferret.auth.mail import MailError, signin_email
from ferret.auth.sessions import (
    SESSION_TTL_SECONDS,
    SessionUser,
    create_session,
    delete_session,
)
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


def render(
    request: Request, state: str, *, email: str = "", error: str | None = None, status: int = 200
) -> Response:
    return templates.TemplateResponse(
        request,
        "signin.html",
        {"state": state, "email": email, "error": error, "csrf_token": request.state.csrf_token},
        status_code=status,
    )


@router.get("/signin")
def signin_page(request: Request, user: SessionUser | None = Depends(current_user)) -> Response:
    if user is not None:
        return RedirectResponse("/", status_code=303)
    return render(request, "form")


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


def _get_or_create_user(request: Request, conn: sqlite3.Connection, email: str) -> str:
    user = control.get_user_by_email(conn, email)
    if user is not None:
        return user["id"]
    state = request.app.state
    try:
        user_id, dek = control.create_user(conn, state.kek, email, now=now(request))
    except sqlite3.IntegrityError:
        # Two first sign-ins for the same email raced; the other one created the account.
        user = control.get_user_by_email(conn, email)
        assert user is not None
        return user["id"]
    open_user_db(state.settings.users_dir, user_id, dek).close()
    return user_id


@router.post("/signout", dependencies=[Depends(verify_csrf)])
def sign_out(request: Request, conn: sqlite3.Connection = Depends(control_conn)) -> Response:
    delete_session(conn, request.cookies.get(SESSION_COOKIE))
    response = RedirectResponse("/signin", status_code=303)
    clear_cookie(response, SESSION_COOKIE)
    return response
