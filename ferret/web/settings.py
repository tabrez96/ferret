"""S05 Settings: the page, and replacing a saved statement password."""

import sqlite3

from fastapi import APIRouter, Depends, Form, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse

from ferret import jobs
from ferret.auth.sessions import SessionUser, end_all_sessions
from ferret.passwords import load_password_rows, password_label, replace_password
from ferret.web.security import (
    SESSION_COOKIE,
    clear_cookie,
    control_conn,
    now,
    require_user,
    user_db,
    user_dek,
    verify_csrf,
)
from ferret.web.templating import templates

router = APIRouter()

CONFIRM_WORD = "DELETE"


def _back(request: Request) -> Response:
    if request.headers.get("hx-request"):
        return Response(status_code=204, headers={"HX-Redirect": "/settings"})
    return RedirectResponse("/settings", status_code=303)


def _gmail_status(db) -> dict | None:
    row = db.execute("SELECT email, status FROM gmail_account WHERE id = 1").fetchone()
    return None if row is None else {"email": row["email"], "status": row["status"]}


def _page(request: Request, user: SessionUser, db, dialog: str | None = None, **extra) -> Response:
    context = {
        "active_nav": "settings",
        "user": user,
        "csrf_token": request.state.csrf_token,
        "rows": load_password_rows(db),
        "gmail": _gmail_status(db),
        "dialog": dialog,
    }
    return templates.TemplateResponse(request, "settings.html", context | extra)


def _dialog(request: Request, user: SessionUser, db, name: str, context: dict) -> Response:
    if request.headers.get("hx-request"):
        context = context | {"csrf_token": request.state.csrf_token}
        return templates.TemplateResponse(request, name, context)
    # No JavaScript: show the whole page with the dialog already open.
    return _page(request, user, db, dialog=name, **context)


@router.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request, user: SessionUser = Depends(require_user), db=Depends(user_db)):
    return _page(request, user, db)


@router.get("/settings/passwords/{password_id}/replace", response_class=HTMLResponse)
def replace_dialog(
    password_id: int,
    request: Request,
    user: SessionUser = Depends(require_user),
    db=Depends(user_db),
):
    card = password_label(db, password_id)
    if card is None:
        return _back(request)
    context = {"password_id": password_id, "card": card, "error": False}
    return _dialog(request, user, db, "password_replace.html", context)


@router.post(
    "/settings/passwords/{password_id}/replace",
    response_class=HTMLResponse,
    dependencies=[Depends(verify_csrf)],
)
def replace(
    password_id: int,
    request: Request,
    password: str = Form(""),
    user: SessionUser = Depends(require_user),
    dek: bytes = Depends(user_dek),
    db=Depends(user_db),
):
    card = password_label(db, password_id)
    if card is None:
        return _back(request)
    if password.strip() == "":
        # 200: the re-rendered form is the expected response, not an error.
        context = {"password_id": password_id, "card": card, "error": True}
        return _dialog(request, user, db, "password_replace.html", context)
    replace_password(db, dek, password_id, password, now=now(request))
    return _back(request)


def _account_counts(db) -> dict:
    return {
        "statements": db.execute("SELECT count(*) FROM statements").fetchone()[0],
        "transactions": db.execute("SELECT count(*) FROM transactions").fetchone()[0],
        "passwords": db.execute("SELECT count(*) FROM statement_passwords").fetchone()[0],
    }


@router.get("/settings/account/delete", response_class=HTMLResponse)
def delete_dialog(request: Request, user: SessionUser = Depends(require_user), db=Depends(user_db)):
    context = {"counts": _account_counts(db), "error": False}
    return _dialog(request, user, db, "delete_account.html", context)


@router.post(
    "/settings/account/delete",
    response_class=HTMLResponse,
    dependencies=[Depends(verify_csrf)],
)
def delete_account(
    request: Request,
    confirm: str = Form(""),
    user: SessionUser = Depends(require_user),
    db=Depends(user_db),
    conn: sqlite3.Connection = Depends(control_conn),
):
    if confirm.strip() != CONFIRM_WORD:
        context = {"counts": _account_counts(db), "error": True}
        return _dialog(request, user, db, "delete_account.html", context)
    end_all_sessions(conn, user.user_id)
    jobs.enqueue(conn, "delete_account", user_id=user.user_id, now=now(request))
    target = "/signin?deleted=1"
    if request.headers.get("hx-request"):
        response = Response(status_code=204, headers={"HX-Redirect": target})
    else:
        response = RedirectResponse(target, status_code=303)
    clear_cookie(response, SESSION_COOKIE)
    return response
