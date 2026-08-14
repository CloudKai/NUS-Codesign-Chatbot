from typing import Any
from collections import OrderedDict
from strands import Agent
import asyncio
import os
from strands.tools.executors import SequentialToolExecutor
from strands.types.exceptions import EventLoopException
from hooks.execution_limits import ExecutionLimitExceeded, ExecutionLimitsHook
from strands.agent.conversation_manager.sliding_window_conversation_manager import SlidingWindowConversationManager
from bedrock_agentcore.runtime import BedrockAgentCoreApp
from bedrock_agentcore.memory.integrations.strands.config import AgentCoreMemoryConfig
from bedrock_agentcore.memory.integrations.strands.session_manager import AgentCoreMemorySessionManager
from model.load import load_model
from mcp_client.client import get_all_gateway_mcp_clients
import phases

app = BedrockAgentCoreApp()
log = app.logger

# Define MCP clients for all configured MCP servers (gateways and/or remote MCP)
mcp_clients = []
mcp_clients += get_all_gateway_mcp_clients()

_INLINE_FUNCTION_NAMES = set()

# Three specialist phases (see phases.py), picked deterministically by the caller via
# payload["phase"] rather than an LLM router. Only Q&A gets the knowledge-base gateway tool --
# coaching and scoring reason over conversation history alone, so they get no tools.
PHASE_TOOLS = {
    phases.PHASE_QA: [c for c in mcp_clients if c],
    phases.PHASE_COACHING: [],
    phases.PHASE_SCORING: [],
}


def _make_conversation_manager():
    return SlidingWindowConversationManager(**{"window_size":150}, per_turn=True)

# Conversation history now lives in AgentCore Memory (durable, keyed by actor_id + session_id --
# see build_specialist_agent), not in this process, so it survives cold starts and works regardless
# of which Runtime instance handles a given request. The conversation manager + execution-limits
# hook stay in-process per session_id (best-effort; resets on cold start) since they govern a single
# instance's live tool-loop rather than persisted state; reusing them across phase switches keeps the
# 75-iteration/1hr cap in ExecutionLimitsHook session-wide instead of resetting every turn. The cache
# is bounded to 128 sessions with LRU eviction so a single process serving many sessions cannot grow
# without limit.
def session_store_factory():
    cache = OrderedDict()
    def get_or_create_session_state(session_id):
        if session_id in cache:
            cache.move_to_end(session_id)
            return cache[session_id]
        if len(cache) >= 128:
            cache.popitem(last=False)
        cache[session_id] = {
            "conversation_manager": _make_conversation_manager(),
            "hook": ExecutionLimitsHook(max_iterations=75, timeout_seconds=3600),
        }
        return cache[session_id]
    return get_or_create_session_state
get_or_create_session_state = session_store_factory()


def build_specialist_agent(session_id: str, actor_id: str, phase: str, topic: str | None) -> Agent:
    state = get_or_create_session_state(session_id)
    memory_config = AgentCoreMemoryConfig(
        memory_id=os.environ["MEMORY_CHAT_HISTORY_ID"],
        session_id=session_id,
        actor_id=actor_id,
    )
    session_manager = AgentCoreMemorySessionManager(
        memory_config,
        region_name=os.environ.get("AWS_REGION", os.environ.get("AWS_DEFAULT_REGION")),
    )
    return Agent(
        model=load_model(),
        system_prompt=phases.build_system_prompt(phase, topic),
        tools=PHASE_TOOLS.get(phase, PHASE_TOOLS[phases.DEFAULT_PHASE]),
        session_manager=session_manager,
        conversation_manager=state["conversation_manager"],
        tool_executor=SequentialToolExecutor(),
        callback_handler=None,
        hooks=[state["hook"]],
    )


def strip_trailing_tool_use(messages: Any) -> list[dict]:
    """Strip toolUse blocks from the tail until the last message has none."""
    if not isinstance(messages, list):
        raise ValueError("messages must be a list")

    messages = list(messages)
    while messages:
        last = messages[-1]
        if not isinstance(last, dict):
            raise ValueError("each message must be an object")
        original_content = last.get("content", [])
        if not isinstance(original_content, list) or not all(isinstance(block, dict) for block in original_content):
            raise ValueError("each message content value must be a list of content blocks")

        content = [block for block in original_content if "toolUse" not in block]
        if len(content) == len(original_content):
            break
        if content:
            messages[-1] = {**last, "content": content}
            break
        messages.pop()

    return messages


def _extract_prompt(payload: dict):
    """Accept validated harness messages, tool results, or a plain prompt string."""
    if not isinstance(payload, dict):
        raise ValueError("payload must be a JSON object")
    if "messages" in payload:
        return strip_trailing_tool_use(payload["messages"])
    if "tool_results" in payload:
        tool_results = payload["tool_results"]
        if not isinstance(tool_results, list) or not all(
            isinstance(tool_result, dict) and isinstance(tool_result.get("toolUseId"), str)
            for tool_result in tool_results
        ):
            raise ValueError("tool_results must contain objects with a toolUseId string")
        return [{"role": "user", "content": [{"toolResult": {
            "toolUseId": tr["toolUseId"],
            "status": tr.get("status", "success"),
            "content": tr.get("content", []),
        }} for tr in tool_results]}]
    prompt = payload.get("prompt", "")
    if not isinstance(prompt, str):
        raise ValueError("prompt must be a string")
    return prompt


def _has_inline_function_call(messages) -> bool:
    """Return True if messages contains an assistant toolUse for an inline function tool."""
    if not _INLINE_FUNCTION_NAMES or not isinstance(messages, list):
        return False
    for msg in messages:
        if msg.get("role") == "assistant":
            for block in msg.get("content", []):
                if isinstance(block, dict) and block.get("toolUse", {}).get("name") in _INLINE_FUNCTION_NAMES:
                    return True
    return False


def _is_inline_function_call(event: dict) -> bool:
    """Check if a contentBlockStart event is for an inline function tool."""
    if not _INLINE_FUNCTION_NAMES:
        return False
    cbs = event.get("contentBlockStart", {})
    start = cbs.get("start", {})
    tool_use = start.get("toolUse") if isinstance(start, dict) else None
    return tool_use is not None and tool_use.get("name") in _INLINE_FUNCTION_NAMES



@app.entrypoint
async def invoke(payload, context):
    log.info("Invoking Agent.....")


    session_id = getattr(context, 'session_id', 'default-session')
    prompt = _extract_prompt(payload)
    phase = payload.get("phase", phases.DEFAULT_PHASE)
    topic = payload.get("topic")
    # No inbound-identity plumbing (Cognito claims, etc.) reaches this entrypoint today -- the
    # caller (post-Cognito-login frontend) must tell us who's asking. Falls back to session_id so
    # test scripts without a student_id still get a working, if anonymous, memory scope.
    actor_id = payload.get("student_id", session_id)
    agent = build_specialist_agent(session_id, actor_id, phase, topic)


    timeout_seconds = 3600
    timeout_fired = False
    watchdog_task = None
    if timeout_seconds is not None:
        async def _timeout_watchdog():
            nonlocal timeout_fired
            await asyncio.sleep(timeout_seconds)
            timeout_fired = True
            agent.cancel()
        watchdog_task = asyncio.create_task(_timeout_watchdog())

    try:
        async for event in agent.stream_async(
            prompt,
        ):
            if not isinstance(event, dict) or "event" not in event:
                continue
            cbs = event["event"].get("contentBlockStart")
            if cbs is not None and not cbs.get("start"):
                continue
            yield event

        if timeout_fired:
            yield {"event": {"messageStop": {"stopReason": "timeout_exceeded"}}}
    except EventLoopException as e:
        if isinstance(e.original_exception, ExecutionLimitExceeded):
            yield {"event": {"messageStop": {"stopReason": str(e.original_exception)}}}
            return
        raise
    finally:
        if watchdog_task is not None:
            watchdog_task.cancel()
            try:
                await watchdog_task
            except asyncio.CancelledError:
                pass


if __name__ == "__main__":
    app.run()
