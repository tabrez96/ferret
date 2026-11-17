"""The MCP server: five read-only tools behind bearer-token auth, served at /mcp."""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import anyio.to_thread
from mcp.server.fastmcp import Context, FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import Receive, Scope, Send

from ferret import control
from ferret.mcp import tools
from ferret.mcp.auth import MCP_WINDOW_SECONDS, admit, bearer_token, find_token
from ferret.userdb import open_user_db

MCP_PATH = "/mcp"
SCOPE_KEY = "ferret.mcp_user"


@dataclass(frozen=True)
class McpUser:
    users_dir: Path
    user_id: str
    dek: bytes


def _with_db(user: McpUser, fn: Callable[..., dict], *args) -> dict:
    """Open the user's DB, run one query and close it, all in the same worker thread."""
    db = open_user_db(user.users_dir, user.user_id, user.dek)
    try:
        return fn(db, *args)
    finally:
        db.close()


async def _run(ctx: Context, fn: Callable[..., dict], *args) -> dict:
    """Read the caller on the event loop, then do the blocking DB work off it."""
    user: McpUser = ctx.request_context.request.scope[SCOPE_KEY]
    return await anyio.to_thread.run_sync(_with_db, user, fn, *args)


def build_server() -> FastMCP:
    server = FastMCP(
        "Ferret",
        stateless_http=True,
        json_response=True,
        streamable_http_path=MCP_PATH,
        # Every request needs a bearer token that a browser never attaches by itself, so
        # DNS rebinding gains nothing. The Host check would also refuse the real domain.
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )

    @server.tool()
    async def list_cards(ctx: Context) -> dict:
        """List your credit cards."""
        return await _run(ctx, tools.list_cards)

    @server.tool()
    async def list_statements(ctx: Context) -> dict:
        """List your statements, newest first, with their status and totals."""
        return await _run(ctx, tools.list_statements)

    @server.tool()
    async def spending_summary(ctx: Context, month: str, card_id: int | None = None) -> dict:
        """Spending per currency for a month (YYYY-MM), optionally for one card."""
        return await _run(ctx, tools.spending_summary, month, card_id)

    @server.tool()
    async def top_merchants(
        ctx: Context, month: str, card_id: int | None = None, limit: int = 5
    ) -> dict:
        """Merchants you spent the most at in a month (YYYY-MM)."""
        return await _run(ctx, tools.top_merchants, month, card_id, limit)

    @server.tool()
    async def search_transactions(
        ctx: Context,
        query: str = "",
        date_from: str | None = None,
        date_to: str | None = None,
        card_id: int | None = None,
        limit: int = 50,
    ) -> dict:
        """Find transactions by merchant text and date range (YYYY-MM-DD)."""
        return await _run(ctx, tools.search_transactions, query, date_from, date_to, card_id, limit)

    return server


class McpAuthApp:
    """ASGI wrapper: only requests with an active, in-limit token reach the MCP app."""

    def __init__(self, web_app) -> None:
        self.web_app = web_app  # app.state is filled in by the lifespan, so read it per request

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.web_app.state.mcp_app(scope, receive, send)
            return
        token = bearer_token(Headers(scope=scope).get("authorization"))
        outcome = await anyio.to_thread.run_sync(self._check, token)
        if outcome == "invalid":
            response = JSONResponse(
                {"error": "invalid_token"},
                status_code=401,
                headers={"WWW-Authenticate": 'Bearer error="invalid_token"'},
            )
        elif outcome == "limited":
            response = JSONResponse(
                {"error": "rate_limited"},
                status_code=429,
                headers={"Retry-After": str(MCP_WINDOW_SECONDS)},
            )
        else:
            scope[SCOPE_KEY] = outcome
            await self.web_app.state.mcp_app(scope, receive, send)
            return
        await response(scope, receive, send)

    def _check(self, token: str | None) -> McpUser | str:
        state = self.web_app.state
        conn = control.connect(state.settings.control_db_path)
        try:
            caller = find_token(conn, token)
            if caller is None:
                return "invalid"
            if not admit(conn, caller, now=state.clock()):
                return "limited"
            dek = control.load_dek(conn, state.kek, caller.user_id)
            return McpUser(state.settings.users_dir, caller.user_id, dek)
        finally:
            conn.close()
