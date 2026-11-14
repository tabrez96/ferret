"""Signed-in pages."""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from ferret.auth.sessions import SessionUser
from ferret.history import load_history
from ferret.money import format_amount
from ferret.web.security import require_user, user_db
from ferret.web.spending_page import build_page, short_day
from ferret.web.templating import templates

router = APIRouter()
templates.env.filters["money"] = format_amount  # {{ minor|money(currency) }}
templates.env.filters["short_day"] = short_day


@router.get("/", response_class=HTMLResponse)
def spending(
    request: Request,
    month: str | None = None,
    card: str = "",
    user: SessionUser = Depends(require_user),
    db=Depends(user_db),
):
    today = datetime.fromtimestamp(request.app.state.clock(), UTC).date()
    return templates.TemplateResponse(
        request,
        "spending.html",
        {
            **build_page(db, month, card, today),
            "active_nav": "spending",
            "user": user,
            "csrf_token": request.state.csrf_token,
        },
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
