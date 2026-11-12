"""Cookies, CSRF protection and the signed-in user."""

import hmac
import sqlite3
from collections.abc import Awaitable, Callable, Iterator

from fastapi import Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from sqlcipher3 import dbapi2 as sqlcipher

from ferret import control
from ferret.auth.sessions import SESSION_TTL_SECONDS, SessionUser, get_session_user
from ferret.auth.tokens import new_token
from ferret.userdb import open_user_db

SESSION_COOKIE = "ferret_session"
CSRF_COOKIE = "ferret_csrf"
CSRF_FIELD = "csrf_token"
CSRF_HEADER = "x-csrf-token"
_MAX_TOKEN_LENGTH = 128


class SignedOutError(Exception):
    """A protected page was requested without a valid session."""


def set_cookie(response: Response, name: str, value: str, max_age: int) -> None:
    response.set_cookie(
        name, value, max_age=max_age, path="/", httponly=True, secure=True, samesite="lax"
    )


def clear_cookie(response: Response, name: str) -> None:
    response.delete_cookie(name, path="/", httponly=True, secure=True, samesite="lax")


async def csrf_cookie_middleware(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    token = request.cookies.get(CSRF_COOKIE)
    is_new = not token or len(token) > _MAX_TOKEN_LENGTH
    if is_new:
        token = new_token()
    request.state.csrf_token = token
    response = await call_next(request)
    if is_new:
        set_cookie(response, CSRF_COOKIE, token, SESSION_TTL_SECONDS)
    return response


async def verify_csrf(request: Request) -> None:
    """Double-submit cookie: the form field (or header) must equal the CSRF cookie."""
    cookie = request.cookies.get(CSRF_COOKIE)
    sent = request.headers.get(CSRF_HEADER) or (await request.form()).get(CSRF_FIELD)
    if not cookie or not isinstance(sent, str) or not hmac.compare_digest(cookie, sent):
        raise HTTPException(403, "This form has expired. Reload the page and try again.")


def control_conn(request: Request) -> Iterator[sqlite3.Connection]:
    conn = control.connect(request.app.state.settings.control_db_path)
    try:
        yield conn
    finally:
        conn.close()


def now(request: Request) -> int:
    return request.app.state.clock()


def current_user(
    request: Request, conn: sqlite3.Connection = Depends(control_conn)
) -> SessionUser | None:
    return get_session_user(conn, request.cookies.get(SESSION_COOKIE), now=now(request))


def require_user(user: SessionUser | None = Depends(current_user)) -> SessionUser:
    if user is None:
        raise SignedOutError
    return user


def user_dek(
    request: Request,
    user: SessionUser = Depends(require_user),
    conn: sqlite3.Connection = Depends(control_conn),
) -> bytes:
    return control.load_dek(conn, request.app.state.kek, user.user_id)


def user_db(
    request: Request,
    user: SessionUser = Depends(require_user),
    dek: bytes = Depends(user_dek),
) -> Iterator[sqlcipher.Connection]:
    db = open_user_db(request.app.state.settings.users_dir, user.user_id, dek)
    try:
        yield db
    finally:
        db.close()


def signed_out_handler(request: Request, exc: SignedOutError) -> Response:
    response = RedirectResponse("/signin", status_code=303)
    clear_cookie(response, SESSION_COOKIE)
    return response
