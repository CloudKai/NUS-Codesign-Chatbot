"""Decode the runtime's SSE wire protocol without buffering the model reply.

Only top-level response_text from structured tool-input fragments reaches the
application's provisional reply sink. Final payload validation remains with the
provider; private structured fields never become student-facing deltas.
"""
from __future__ import annotations

import codecs
import json
from collections.abc import Callable
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from backend.coaching.cancellation import check_turn_cancelled, register_stream_closer
from backend.coaching.reply_text import ReplyTextExtractor

_MAX_STREAM_BYTES = 2_000_000


class RuntimeModelDelta(BaseModel):
    """One actual model tool-input fragment, before structured validation."""

    model_config = ConfigDict(extra="forbid")
    event: Literal["model_delta"]
    tool_id: str = Field(max_length=200)
    input: str = Field(max_length=_MAX_STREAM_BYTES)


class RuntimeStreamResult(BaseModel):
    """Terminal runtime result; the existing provider validates its payload."""

    model_config = ConfigDict(extra="forbid")
    event: Literal["result"]
    payload: dict[str, Any]


_FRAME = TypeAdapter(RuntimeModelDelta | RuntimeStreamResult)


def read_runtime_reply_stream(body: Any, emit: Callable[[str | None], None]) -> dict[str, Any]:
    """Consume SDK body chunks incrementally, closing it on success or failure.

    Raises ValueError for malformed/truncated/oversized streams. A replacement
    tool call withdraws the earlier preview before its new text is emitted.
    Only one terminal result is accepted, and nothing may follow it.
    """
    decoder = codecs.getincrementaldecoder("utf-8")("strict")
    buffer = ""
    data: list[str] = []
    total = 0
    result: dict[str, Any] | None = None
    tool_id: str | None = None
    extractor = ReplyTextExtractor()

    def accept() -> None:
        nonlocal result, tool_id, extractor
        if not data:
            return
        if result is not None:
            raise ValueError("Runtime event after terminal result")
        frame = _FRAME.validate_python(json.loads('\n'.join(data)))
        data.clear()
        if isinstance(frame, RuntimeStreamResult):
            result = frame.payload
        else:
            if tool_id is not None and frame.tool_id != tool_id:
                emit(None)
                extractor = ReplyTextExtractor()
            tool_id = frame.tool_id
            text = extractor.feed(frame.input)
            if text:
                emit(text)

    close = getattr(body, "close", None)
    try:
        if callable(close):
            register_stream_closer(close)
        # A one-byte read bound prevents StreamingBody.read(large_amount) from
        # waiting for a full buffer before yielding a small SSE model event.
        for chunk in body.iter_chunks(chunk_size=1):
            check_turn_cancelled()
            total += len(chunk)
            if total > _MAX_STREAM_BYTES:
                raise ValueError("Runtime stream too large")
            buffer += decoder.decode(chunk)
            while '\n' in buffer:
                line, buffer = buffer.split('\n', 1)
                line = line.removesuffix('\r')
                if not line:
                    accept()
                elif line.startswith('data:'):
                    data.append(line[5:].lstrip(' '))
        buffer += decoder.decode(b'', final=True)
        if buffer.strip() or data or result is None:
            raise ValueError("Incomplete runtime stream")
        return result
    finally:
        register_stream_closer(None)
        if callable(close):
            close()
