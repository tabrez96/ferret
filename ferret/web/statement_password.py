"""The S04 dialog: enter a statement's password, or skip the statement."""

from fastapi import APIRouter, Depends, Form, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse

from ferret.auth.sessions import SessionUser
from ferret.history import HistoryRow, load_history, load_row
from ferret.pipeline.locked import (
    NotWaiting,
    WrongPassword,
    has_saved_passwords,
    open_with_password,
    skip_statement,
)
from ferret.web.security import control_conn, now, require_user, user_db, user_dek, verify_csrf
from ferret.web.templating import templates

router = APIRouter()


def _back(request: Request) -> Response:
    if request.headers.get("hx-request"):
        return Response(status_code=204, headers={"HX-Redirect": "/statements"})
    return RedirectResponse("/statements", status_code=303)


def _dialog(
    request: Request, user: SessionUser, db, statement: HistoryRow, *, wrong: bool, changed: bool
) -> Response:
    context = {
        "statement": statement,
        "wrong": wrong,
        "changed": changed,
        "csrf_token": request.state.csrf_token,
    }
    if request.headers.get("hx-request"):
        name = "password_form.html" if wrong else "password_dialog.html"
        return templates.TemplateResponse(request, name, context)
    # No JavaScript: show the whole page with the dialog already open.
    context |= {
        "active_nav": "statements",
        "user": user,
        "rows": load_history(db),
        "dialog": True,
    }
    return templates.TemplateResponse(request, "statements.html", context)


@router.get("/statements/{statement_id}/password", response_class=HTMLResponse)
def password_dialog(
    statement_id: int,
    request: Request,
    user: SessionUser = Depends(require_user),
    db=Depends(user_db),
):
    statement = load_row(db, statement_id)
    if statement is None or statement.status != "needs_password":
        return _back(request)
    return _dialog(request, user, db, statement, wrong=False, changed=False)


@router.post(
    "/statements/{statement_id}/password",
    response_class=HTMLResponse,
    dependencies=[Depends(verify_csrf)],
)
def submit_password(
    statement_id: int,
    request: Request,
    password: str = Form(""),
    user: SessionUser = Depends(require_user),
    dek: bytes = Depends(user_dek),
    db=Depends(user_db),
    conn=Depends(control_conn),
):
    changed = has_saved_passwords(db)
    try:
        open_with_password(
            conn,
            db,
            dek,
            request.app.state.settings.pending_dir,
            user.user_id,
            statement_id,
            password,
            now=now(request),
        )
    except WrongPassword:
        # 200: the re-rendered form is the expected response, not an error.
        statement = load_row(db, statement_id)
        return _dialog(request, user, db, statement, wrong=True, changed=changed)
    except NotWaiting:
        pass
    return _back(request)


@router.post("/statements/{statement_id}/skip", dependencies=[Depends(verify_csrf)])
def skip(
    statement_id: int,
    request: Request,
    user: SessionUser = Depends(require_user),
    db=Depends(user_db),
):
    try:
        skip_statement(db, request.app.state.settings.pending_dir, user.user_id, statement_id)
    except NotWaiting:
        pass
    return _back(request)
