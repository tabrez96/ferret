"""Signed-in pages."""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from ferret.auth.sessions import SessionUser
from ferret.web.security import require_user
from ferret.web.templating import templates

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
def spending(request: Request, user: SessionUser = Depends(require_user)):
    return templates.TemplateResponse(
        request,
        "spending.html",
        {"active_nav": "spending", "user": user, "csrf_token": request.state.csrf_token},
    )
