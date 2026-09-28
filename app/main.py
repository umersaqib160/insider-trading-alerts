from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from .auth import LoginRequired
from .config import Settings, get_settings
from .routes import account, auth, lists
from .web import APP_DIR, is_htmx

SESSION_MAX_AGE = 30 * 24 * 60 * 60


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(title="Behind The Curtain", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.settings = settings

    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.secret_key,
        session_cookie="btc_session",
        max_age=SESSION_MAX_AGE,
        same_site="lax",
        https_only=settings.is_production,
    )
    app.mount("/static", StaticFiles(directory=APP_DIR / "static"), name="static")
    app.include_router(auth.router)
    app.include_router(lists.router)
    app.include_router(account.router)

    @app.exception_handler(LoginRequired)
    async def _login_required(request: Request, exc: LoginRequired) -> Response:
        if is_htmx(request):
            return Response(status_code=200, headers={"HX-Redirect": "/login"})
        return RedirectResponse("/login", status_code=303)

    @app.get("/healthz", include_in_schema=False)
    def healthz() -> PlainTextResponse:
        return PlainTextResponse("ok")

    return app


app = create_app()
