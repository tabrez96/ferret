"""S03 uploads: check each PDF, store it encrypted and queue it for reading."""

import logging
from dataclasses import dataclass
from typing import Annotated

from fastapi import APIRouter, Depends, File, Request, UploadFile
from fastapi.responses import HTMLResponse
from starlette.middleware.body_limit import RequestBodyLimitMiddleware

from ferret import ratelimit
from ferret.auth.sessions import SessionUser
from ferret.history import load_history
from ferret.pipeline import submit_statement
from ferret.web.security import control_conn, now, require_user, user_db, user_dek, verify_csrf
from ferret.web.templating import templates

logger = logging.getLogger(__name__)

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_BODY_BYTES = 50 * 1024 * 1024
UPLOAD_LIMIT = 30
UPLOAD_WINDOW_SECONDS = 3600
PDF_MAGIC = b"%PDF-"
UPLOAD_PATH = "/statements/upload"


@dataclass(frozen=True)
class Notice:
    title: str
    body: str


RATE_NOTICE = Notice(
    "That's a lot of statements in one hour.",
    "You can upload 30 files an hour. Files after the limit weren't uploaded. Try again later.",
)


class UploadBodyLimit:
    """ASGI middleware: refuse upload bodies over MAX_BODY_BYTES before the form is parsed."""

    def __init__(self, app):
        self.app = app
        self.limited = RequestBodyLimitMiddleware(app, max_body_size=MAX_BODY_BYTES)

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope["path"] == UPLOAD_PATH:
            return await self.limited(scope, receive, send)
        await self.app(scope, receive, send)


router = APIRouter()


def check_file(name: str, data: bytes) -> Notice | None:
    """None when the file may be uploaded, otherwise the per-file notice."""
    if len(data) > MAX_UPLOAD_BYTES:
        return Notice("That file is too big.", f"“{name}” is over 10 MB, so it wasn't uploaded.")
    if not data.startswith(PDF_MAGIC):
        return Notice(
            "This doesn't look like a credit card statement.",
            f"“{name}” isn't a PDF, so it wasn't uploaded.",
        )
    return None


@router.post(UPLOAD_PATH, response_class=HTMLResponse, dependencies=[Depends(verify_csrf)])
def upload(
    request: Request,
    file: Annotated[list[UploadFile], File()],
    user: SessionUser = Depends(require_user),
    dek: bytes = Depends(user_dek),
    db=Depends(user_db),
    conn=Depends(control_conn),
):
    t = now(request)
    pending_dir = request.app.state.settings.pending_dir
    notices: list[Notice] = []
    status = 200
    accepted = 0
    for item in file:
        data = item.file.read(MAX_UPLOAD_BYTES + 1)
        notice = check_file(item.filename or "This file", data)
        if notice:
            notices.append(notice)
            continue
        if not ratelimit.allow(
            conn, f"upload:{user.user_id}", now=t, limit=UPLOAD_LIMIT, window=UPLOAD_WINDOW_SECONDS
        ):
            notices.append(RATE_NOTICE)
            status = 429
            break
        submit_statement(
            conn, db, dek, pending_dir, user.user_id, data, source="upload", source_ref=None, now=t
        )
        accepted += 1
    if status != 429 and accepted == 0:
        status = 400
    logger.info("upload: %d accepted, %d refused", accepted, len(notices))
    return templates.TemplateResponse(
        request,
        "upload_result.html",
        {"notices": notices, "rows": load_history(db)},
        status_code=status,
    )
