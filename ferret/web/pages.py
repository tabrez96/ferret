"""Signed-in pages."""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from ferret.auth.sessions import SessionUser
from ferret.history import load_history
from ferret.web.security import require_user, user_db
from ferret.web.templating import templates

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
def spending(request: Request, user: SessionUser = Depends(require_user)):
    return templates.TemplateResponse(
        request,
        "spending.html",
        {"active_nav": "spending", "user": user, "csrf_token": request.state.csrf_token},
    )


@router.get("/statements", response_class=HTMLResponse)
def statements(request: Request, user: SessionUser = Depends(require_user), db=Depends(user_db)):
    return templates.TemplateResponse(
        request,
        "statements.html",
        {
            "active_nav": "statements",
            "user": user,
            "csrf_token": request.state.csrf_token,
            "rows": load_history(db),
        },
    )
