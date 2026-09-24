"""One Core lifespan with independent browser and internal TLS listeners."""

import asyncio
import contextlib

import uvicorn
from starlette.responses import JSONResponse


class InternalAPI:
    """No browser UI, cookies or proxy trust on the internal enrollment listener."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        allowed = {
            ("POST", "/api/v1/hosts/pair"),
            ("GET", "/api/v1/health"),
        }
        if scope["type"] != "http":
            if scope["type"] == "websocket":
                await send({"type": "websocket.close", "code": 1008})
            return
        if (scope["method"], scope["path"]) not in allowed:
            await JSONResponse({"error": "Internal endpoint only"}, status_code=404)(
                scope, receive, send
            )
            return
        scope = dict(scope)
        # TLS is terminated here, not asserted by callers. Do not share proxy trust.
        scope["headers"] = [
            (k, v) for k, v in scope["headers"] if not k.lower().startswith(b"x-forwarded-")
        ]
        await self.app(scope, receive, send)


def browser_server_config(app, config, host, port):
    """Direct TLS on the existing browser port; no redirect listener or proxy."""
    return uvicorn.Config(
        app,
        host=host,
        port=port,
        access_log=False,
        proxy_headers=False,
        workers=1,
        lifespan="off" if config.internal_tls_cert else "auto",
        ssl_certfile=str(config.browser_tls_cert) if config.browser_tls_cert else None,
        ssl_keyfile=str(config.browser_tls_key) if config.browser_tls_key else None,
    )


async def serve(app, config, host, port):
    primary = uvicorn.Server(browser_server_config(app, config, host, port))
    # Invalid/missing key material must never silently fall back to plaintext.
    primary.config.load()
    if not config.internal_tls_cert:
        await primary.serve()
        return
    internal = uvicorn.Server(
        uvicorn.Config(
            InternalAPI(app),
            host=config.internal_tls_host,
            port=config.internal_tls_port,
            access_log=False,
            proxy_headers=False,
            lifespan="off",
            workers=1,
            ssl_certfile=str(config.internal_tls_cert),
            ssl_keyfile=str(config.internal_tls_key),
        )
    )
    # Validate certificate/key before starting any listener.
    internal.config.load()
    async with app.router.lifespan_context(app):
        tasks = [asyncio.create_task(server.serve()) for server in (primary, internal)]
        try:
            await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        finally:
            primary.should_exit = internal.should_exit = True
            for task in tasks:
                with contextlib.suppress(asyncio.CancelledError):
                    await task
