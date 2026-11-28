"""Self-host only: live thermometer readings from the home network to the page.

Anything at home that can read the probe posts each reading here (a Home Assistant
automation on its Inkbird integration, a script on the probe's hub); the page
listens on a server-sent event stream and logs it into the cook. Only
`sousvide.selfhost` mounts this router: the public API never takes readings,
because a probe is on someone's kitchen network, not on the internet.
"""
import asyncio
import json
import time
from collections.abc import AsyncIterator

from fastapi import APIRouter, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

router = APIRouter()

KEEPALIVE_S = 15  # a comment line this often keeps proxies from closing a quiet stream


class Reading(BaseModel):
    f: float = Field(ge=-40, le=572, description='What the probe reads, in °F')
    probe: str = Field('probe', max_length=40)


class Hub:
    """The latest reading and a bounded queue per open stream. One kitchen, a few listeners."""

    def __init__(self) -> None:
        self.latest: dict | None = None
        self.listeners: set[asyncio.Queue[dict]] = set()

    def publish(self, reading: Reading) -> None:
        self.latest = {'f': reading.f, 'probe': reading.probe, 'at': round(time.time(), 1)}
        for queue in self.listeners:
            if queue.full():  # a stalled listener drops its oldest reading, never blocks the post
                queue.get_nowait()
            queue.put_nowait(self.latest)

    async def events(self, queue: asyncio.Queue[dict]) -> AsyncIterator[str]:
        """The stream for one listener: the latest reading at once, then each new one."""
        self.listeners.add(queue)
        try:
            if self.latest:
                yield f'data: {json.dumps(self.latest)}\n\n'
            while True:
                try:
                    reading = await asyncio.wait_for(queue.get(), KEEPALIVE_S)
                except TimeoutError:
                    yield ': keepalive\n\n'
                else:
                    yield f'data: {json.dumps(reading)}\n\n'
        finally:
            self.listeners.discard(queue)


hub = Hub()


@router.post('/probe', status_code=204)
def post_reading(reading: Reading) -> Response:
    hub.publish(reading)
    return Response(status_code=204)


@router.get('/probe/stream')
def stream() -> StreamingResponse:
    return StreamingResponse(hub.events(asyncio.Queue(maxsize=16)), media_type='text/event-stream',
                             headers={'Cache-Control': 'no-store', 'X-Accel-Buffering': 'no'})
