from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from ferret import __version__
from ferret.web.templating import STATIC_DIR


def create_app() -> FastAPI:
    app = FastAPI(title="Ferret", version=__version__, docs_url=None, redoc_url=None)
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
