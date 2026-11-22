"""Disposable mock-only HTTP relay for rendered incremental-reply verification.

All workspace paths must be explicitly under a temporary directory. The relay
slows delivery of real mock NDJSON events; it never changes model output or
claims to measure live LLM latency. Run with uvicorn on a disposable port.
"""
from __future__ import annotations

import asyncio
import json
import os
import tempfile
from pathlib import Path

from starlette.types import ASGIApp, Message, Receive, Scope, Send


def _require_disposable_mock() -> None:
    root = Path(os.environ.get('APP_DATA_DIR', '/invalid')).resolve()
    temporary = (Path('/tmp').resolve(), Path(tempfile.gettempdir()).resolve())
    if os.environ.get('MODEL_PROVIDER') != 'mock' or not any(root.is_relative_to(p) for p in temporary):
        raise RuntimeError('Streaming fixture requires an explicit temporary mock workspace')
    for key in ('APP_DATABASE_PATH', 'APP_FILES_DIR', 'APP_WORKSPACES_DIR', 'LECTURE_NOTES_DIR'):
        if not os.environ.get(key) or not Path(os.environ[key]).resolve().is_relative_to(root):
            raise RuntimeError('All fixture workspace paths must be explicit and temporary')


_require_disposable_mock()

from backend.http.app import create_app


class DelayedNDJSON:
    """Delay actual mock reply fragments so the browser can observe growing text."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Relay ASGI output unchanged except for delivery timing of reply deltas."""
        ndjson = False
        buffer = b''

        async def relay(message: Message) -> None:
            nonlocal ndjson, buffer
            if message['type'] == 'http.response.start':
                ndjson = any(key.lower() == b'content-type' and b'application/x-ndjson' in value for key, value in message['headers'])
            if message['type'] != 'http.response.body' or not ndjson:
                await send(message)
                return
            buffer += message.get('body', b'')
            while b'\n' in buffer:
                line, buffer = buffer.split(b'\n', 1)
                if line:
                    if json.loads(line).get('event') == 'reply_delta':
                        await asyncio.sleep(.15)
                    await send({'type': 'http.response.body', 'body': line + b'\n', 'more_body': True})
            if not message.get('more_body', False):
                await send({'type': 'http.response.body', 'body': buffer, 'more_body': False})
                buffer = b''

        await self.app(scope, receive, relay)


app = DelayedNDJSON(create_app())
