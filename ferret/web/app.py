import time
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.routing import Route

from ferret import __version__, control
from ferret.auth.google import GoogleOAuth, google_from_settings
from ferret.auth.mail import Mailer, mailer_from_settings
from ferret.config import Settings
from ferret.keys import load_master_key
from ferret.logging import setup_logging
from ferret.mcp.server import MCP_PATH, McpAuthApp, build_server
from ferret.web import pages, settings, signin, statement_password, upload
from ferret.web.headers import security_headers_middleware
from ferret.web.security import SignedOutError, csrf_cookie_middleware, signed_out_handler
from ferret.web.templating import STATIC_DIR

Clock = Callable[[], int]


def create_app(
    *,
    clock: Clock | None = None,
    mailer: Mailer | None = None,
    google: GoogleOAuth | None = None,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        settings = Settings.from_env()
        setup_logging()
        # Raises MasterKeyError when the key is missing or unusable: the app refuses to start.
        app.state.kek = load_master_key(settings.master_key_file, settings.data_dir)
        app.state.settings = settings
        app.state.clock = clock or (lambda: int(time.time()))
        app.state.mailer = mailer or mailer_from_settings(settings)
        app.state.google = google or google_from_settings(settings)
        settings.users_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        control.connect(settings.control_db_path).close()
        # Built per lifespan: a session manager runs once, and a test may start one app twice.
        mcp_server = build_server()
        app.state.mcp_app = mcp_server.streamable_http_app()
        async with mcp_server.session_manager.run():
            yield

    app = FastAPI(
        title="Ferret", version=__version__, docs_url=None, redoc_url=None, lifespan=lifespan
    )
    # Last added is outermost: the body limit sits inside so its 413 still gets the headers.
    app.add_middleware(upload.UploadBodyLimit)
    app.middleware("http")(csrf_cookie_middleware)
    app.middleware("http")(security_headers_middleware)
    app.add_exception_handler(SignedOutError, signed_out_handler)
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(signin.router)
    app.include_router(pages.router)
    app.include_router(statement_password.router)
    app.include_router(upload.router)
    app.include_router(settings.router)
    # A Route, not a Mount: a Mount would redirect POST /mcp to /mcp/.
    # The MCP app routes MCP_PATH itself.
    app.router.routes.append(Route(MCP_PATH, McpAuthApp(app), name="mcp"))
    return app


app = create_app()
