"""Open browser event streams must not hold updates until Docker's stop timeout."""

import asyncio
import contextlib
import socket
from types import SimpleNamespace

import httpx
import uvicorn
from fastapi import FastAPI, Request
from mediahub.api import stream
from mediahub.events import EventBus
from mediahub.serve import CoreServer


def test_shutdown_drains_open_event_stream_and_finishes_lifespan():
    async def run():
        closed = asyncio.Event()

        @contextlib.asynccontextmanager
        async def lifespan(app):
            yield
            closed.set()

        app = FastAPI(lifespan=lifespan)
        bus = EventBus(None)
        app.state.services = SimpleNamespace(
            events=bus,
            snapshot={},
            apps=SimpleNamespace(list=lambda: []),
            auth=SimpleNamespace(authenticate=lambda token: None),
            config=SimpleNamespace(sample_seconds=60),
        )

        @app.get("/events")
        async def events(request: Request):
            return await stream(request, user={})

        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen()
            port = listener.getsockname()[1]
            server = CoreServer(uvicorn.Config(app, access_log=False, log_level="error"), app)
            task = asyncio.create_task(server.serve(sockets=[listener]))
            try:
                async with asyncio.timeout(5):
                    while not server.started:
                        await asyncio.sleep(0.01)
                    async with httpx.AsyncClient() as client:
                        async with client.stream(
                            "GET", f"http://127.0.0.1:{port}/events"
                        ) as response:
                            lines = response.aiter_lines()
                            assert await anext(lines) == "retry: 5000"
                            assert len(bus.subscribers) == 1
                            server.should_exit = True
                            # Keep the client connected. The server must end the stream itself.
                            async for _ in lines:
                                pass
                            await task
                assert closed.is_set()
                assert not bus.subscribers
                assert bus.stopping
            finally:
                if not task.done():
                    task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await task

    asyncio.run(run())


def test_stop_wakes_full_event_queues():
    bus = EventBus(None)
    queue = asyncio.Queue(maxsize=1)
    bus.subscribers.add(queue)
    bus.publish("system.status", {})
    bus.close_streams()
    bus.close_streams()
    assert bus.stopping
    assert queue.get_nowait()["type"] == "system.stopping"
