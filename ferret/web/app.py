import time
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from ferret import __version__, control
from ferret.auth.google import GoogleOAuth, google_from_settings
from ferret.auth.mail import Mailer, mailer_from_settings
from ferret.config import Settings
from ferret.keys import load_master_key
from ferret.logging import setup_logging
from ferret.web import pages, settings, signin, statement_password
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
        yield

    app = FastAPI(
        title="Ferret", version=__version__, docs_url=None, redoc_url=None, lifespan=lifespan
    )
    app.middleware("http")(csrf_cookie_middleware)
    app.add_exception_handler(SignedOutError, signed_out_handler)
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(signin.router)
    app.include_router(pages.router)
    app.include_router(statement_password.router)
    app.include_router(settings.router)
    return app


app = create_app()
