"""Signed-in pages."""

from datetime import UTC, date, datetime

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from ferret.auth.sessions import SessionUser
from ferret.history import load_history
from ferret.money import format_amount
from ferret.web.security import require_user, user_db
from ferret.web.spending_page import (
    build_page,
    parse_offset,
    resolve_filters,
    short_day,
    tx_page,
)
from ferret.web.templating import templates

router = APIRouter()
templates.env.filters["money"] = format_amount  # {{ minor|money(currency) }}
templates.env.filters["short_day"] = short_day


def _today(request: Request) -> date:
    return datetime.fromtimestamp(request.app.state.clock(), UTC).date()


@router.get("/", response_class=HTMLResponse)
def spending(
    request: Request,
    month: str | None = None,
    card: str = "",
    q: str = "",
    user: SessionUser = Depends(require_user),
    db=Depends(user_db),
):
    return templates.TemplateResponse(
        request,
        "spending.html",
        {
            **build_page(db, month, card, _today(request), q),
            "active_nav": "spending",
            "user": user,
            "csrf_token": request.state.csrf_token,
        },
    )


@router.get("/transactions", response_class=HTMLResponse)
def transactions(
    request: Request,
    month: str | None = None,
    card: str = "",
    q: str = "",
    user: SessionUser = Depends(require_user),
    db=Depends(user_db),
):
    m, card_id = resolve_filters(db, month, card, _today(request))
    return templates.TemplateResponse(request, "spending_tx.html", tx_page(db, m, card_id, q, 0))


@router.get("/transactions/rows", response_class=HTMLResponse)
def transaction_rows(
    request: Request,
    month: str | None = None,
    card: str = "",
    q: str = "",
    offset: str = "",
    user: SessionUser = Depends(require_user),
    db=Depends(user_db),
):
    m, card_id = resolve_filters(db, month, card, _today(request))
    ctx = tx_page(db, m, card_id, q, parse_offset(offset))
    return templates.TemplateResponse(request, "spending_tx_rows.html", ctx)


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
