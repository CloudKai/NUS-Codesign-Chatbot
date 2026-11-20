"""Live-run guards and request builders shared by the model-call evals.

Importing this module starts no call. ``check_live_model_request`` and
``select_live_rows`` only validate; ``LiveFastChatBridge``, ``build_live_request``
and ``_live_eval_provider`` build payloads and import the backend lazily. The
commands that actually send requests (``evaluate_retrieval --live-model`` and
``benchmark_agentcore_vs_converse``) stay the only owners of the clients.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from scripts.evals.lib.fixtures import DECISIONS, MESSAGE_CATEGORIES
from scripts.evals.lib.gate import GateDecision
from scripts.evals.lib.metrics import evenly_spaced_indices


def _refuse_unknown(flag: str, unknown: Sequence[str]) -> None:
    if unknown:
        more = f" and {len(unknown) - 5} more" if len(unknown) > 5 else ""
        raise LiveRunRefused(f"unknown value(s) in {flag}: {', '.join(unknown[:5])}{more}")


def select_live_rows(
    messages: Sequence[Mapping[str, Any]],
    *,
    ids: Sequence[str] | None = None,
    categories: Sequence[str] | None = None,
    expected_decision: str | None = None,
    skip_sample: int = 0,
) -> list[Mapping[str, Any]]:
    """Select the gate rows a live-model run sends, in file order.

    Order: (a) with neither ``ids`` nor ``categories`` start from all rows,
    else keep rows whose id **or** category is listed (union); (b)
    ``expected_decision`` keeps only rows with that label; (c) ``skip_sample``
    adds that many ``skip`` rows not already selected, chosen with
    ``evenly_spaced_indices`` over that pool in file order. ``None`` for a
    filter means "not given"; ``--max-live-calls`` applies later.

    Raises:
        LiveRunRefused: On an unknown id or category, an empty ``ids`` or
            ``categories`` list, a bad ``expected_decision``, a negative
            ``skip_sample``, or an empty selection.
    """
    if ids is not None and not ids:
        raise LiveRunRefused("--ids was given but names no id")
    if categories is not None and not categories:
        raise LiveRunRefused("--categories was given but names no category")
    if expected_decision is not None and expected_decision not in DECISIONS:
        raise LiveRunRefused(f"--expected-decision must be one of {', '.join(sorted(DECISIONS))}")
    if skip_sample < 0:
        raise LiveRunRefused("--skip-sample must be 0 or more")
    wanted_ids = set(ids or ())
    wanted_categories = set(categories or ())
    known_ids = {str(row["id"]) for row in messages}
    _refuse_unknown("--ids", [item for item in dict.fromkeys(ids or ()) if item not in known_ids])
    _refuse_unknown(
        "--categories",
        [item for item in dict.fromkeys(categories or ()) if item not in MESSAGE_CATEGORIES],
    )
    if ids is None and categories is None:
        selected = list(messages)
    else:
        selected = [
            row
            for row in messages
            if str(row["id"]) in wanted_ids or str(row["category"]) in wanted_categories
        ]
    if expected_decision is not None:
        selected = [row for row in selected if row["expected_decision"] == expected_decision]
    if skip_sample:
        taken = {str(row["id"]) for row in selected}
        pool = [
            row for row in messages if row["expected_decision"] == "skip" and str(row["id"]) not in taken
        ]
        taken |= {str(pool[i]["id"]) for i in evenly_spaced_indices(len(pool), skip_sample)}
        selected = [row for row in messages if str(row["id"]) in taken]
    if not selected:
        raise LiveRunRefused("the row filters selected no rows")
    return selected


class LiveRunRefused(RuntimeError):
    """Raised when the live Knowledge Base path is requested without approval."""


class LiveCallLimitExceeded(RuntimeError):
    """Raised by the call counter when the approved call limit is reached."""


# One model call per message, sequential, no retries. The gate set has fewer
# than 500 messages, so a higher limit could never be used.
LIVE_MODEL_HARD_CALL_CAP = 500


# Same read timeout as ``AgentCoreCoachProvider`` (``timeout_seconds=110``).
LIVE_MODEL_TIMEOUT_SECONDS = 110.0


# Same output reserve as the fast-chat context planner
# (``_fast_chat_planner_from_settings``: ``output_reserve_tokens=4_000``).
LIVE_MODEL_MAX_OUTPUT_TOKENS = 4_000


# Never invoked: the provider is built only to reuse its payload builder.
_EVAL_RUNTIME_ARN = "eval:runtime-never-invoked"


# Codes and exception classes that mean "credentials or permission": the run
# stops after the first one, because every later call would fail the same way.
AUTH_ACCESS_ERROR_CODES = frozenset(
    {
        "AccessDeniedException",
        "AccessDenied",
        "UnrecognizedClientException",
        "InvalidClientTokenId",
        "ExpiredTokenException",
        "ExpiredToken",
        "AuthFailure",
        "InvalidSignatureException",
        "SignatureDoesNotMatch",
        "UnauthorizedOperation",
        "UnauthorizedException",
    }
)


AUTH_ACCESS_ERROR_CLASSES = frozenset(
    {
        "NoCredentialsError",
        "PartialCredentialsError",
        "TokenRetrievalError",
        "CredentialRetrievalError",
        "NoAuthTokenError",
    }
)


class LiveStructuredOutputError(RuntimeError):
    """The model returned no usable ``FastChatTurnOutput`` tool call.

    ``detail`` holds only safe, structural facts (failure kind, stop reason,
    pydantic error locations and types); never message, reply or tool input
    values.
    """

    def __init__(self, message: str, detail: Mapping[str, Any] | None = None) -> None:
        super().__init__(message)
        self.detail: dict[str, Any] = dict(detail or {})


def check_live_model_request(
    live_model: bool,
    live_kb: bool,
    max_live_calls: int | None,
    *,
    provider: str,
    model_id: str,
    region: str,
) -> int:
    """Validate the live model opt-in and return the approved call limit.

    Makes no network call and imports no AWS library.

    Args:
        live_model: ``--live-model``.
        live_kb: ``--live-kb`` (cannot be combined with the model mode).
        max_live_calls: ``--max-live-calls``.
        provider: Fast-chat provider from settings (``COACHING_MODEL_PROVIDER``).
        model_id: Fast-chat model id from settings (``COACHING_MODEL_ID``).
        region: Model region from settings.

    Raises:
        LiveRunRefused: When the limit is missing or out of range, the mode is
            combined with ``--live-kb``, or the model settings are not a Haiku
            model on the ``bedrock`` provider.
    """
    if live_kb:
        raise LiveRunRefused("--live-model cannot be combined with --live-kb")
    if not live_model:
        raise LiveRunRefused("live model mode was not requested")
    if max_live_calls is None:
        raise LiveRunRefused(
            "--live-model requires --max-live-calls N (1 to "
            f"{LIVE_MODEL_HARD_CALL_CAP}); no call limit was given"
        )
    if not 1 <= max_live_calls <= LIVE_MODEL_HARD_CALL_CAP:
        raise LiveRunRefused(
            f"--max-live-calls must be between 1 and {LIVE_MODEL_HARD_CALL_CAP}"
        )
    if str(provider or "").strip().lower() != "bedrock":
        raise LiveRunRefused(
            "COACHING_MODEL_PROVIDER must be 'bedrock' for the fast-chat model "
            f"(got {provider or 'empty'!r})"
        )
    if "haiku" not in str(model_id or "").lower():
        raise LiveRunRefused(
            "COACHING_MODEL_ID is not set to a Haiku model "
            f"(got {model_id or 'empty'!r}); the fast-chat role is Haiku"
        )
    if not str(region or "").strip():
        raise LiveRunRefused("AGENTCORE_MODEL_REGION (or AWS_REGION) is not set")
    return max_live_calls


def live_model_settings() -> tuple[str, str, str]:
    """Return ``(provider, model_id, region)`` the fast-chat role uses.

    Mirrors ``AgentCoreCoachProvider._role_provider_model("fast_chat")`` and
    the runtime region rule (``AGENTCORE_MODEL_REGION``, then ``AWS_REGION``).
    """
    from backend.settings import settings

    provider = str(settings.coaching_model_provider or "").strip().lower()
    model_id = str(settings.coaching_model_id or "").strip()
    if not (provider and model_id):
        provider = str(settings.agentcore_model_provider or "").strip().lower()
        model_id = str(settings.agentcore_model_id or "").strip()
    region = (
        str(settings.agentcore_model_region or "").strip()
        or str(settings.aws_region or "").strip()
    )
    return provider, model_id, region


def _inline_schema_refs(schema: Mapping[str, Any]) -> dict[str, Any]:
    """Inline ``$ref`` targets and drop ``$defs`` (a tool schema must be flat)."""
    defs = dict(schema.get("$defs") or {})

    def walk(node: Any) -> Any:
        if isinstance(node, Mapping):
            ref = node.get("$ref")
            if isinstance(ref, str) and ref.startswith("#/$defs/"):
                return walk(defs[ref.rsplit("/", 1)[-1]])
            return {key: walk(value) for key, value in node.items() if key != "$defs"}
        if isinstance(node, list):
            return [walk(item) for item in node]
        return node

    return walk(dict(schema))


class LiveFastChatBridge:
    """Run the AgentCore runtime's fast-chat model call straight on Bedrock.

    The runtime (``agentcore_runtime/main.py::fast_chat_invoke``) builds a
    Strands ``Agent`` with ``tools=[]`` and ``structured_output_model=
    FastChatTurnOutput``; Strands forwards that model to Bedrock Converse as
    one forced tool. This class sends the same system prompt, messages and
    tool through ``bedrock-runtime`` ``converse`` without Strands or an
    AgentCore hop. Differences from production, all recorded in the docs: no
    Bedrock guardrail, no prompt-cache point, no structured-output recovery
    turn (a reply without the tool call is a failure), no SDK retries.
    """

    def __init__(self, client: Any, model_id: str) -> None:
        from agentcore_runtime.models import FastChatTurnOutput

        self._client = client
        self._model_id = model_id
        # Bedrock ``stopReason`` of the last call (an enum value, not text).
        self.last_stop_reason: str | None = None
        self._schema = _inline_schema_refs(FastChatTurnOutput.model_json_schema())
        self._description = " ".join(
            (FastChatTurnOutput.__doc__ or "").split("\n\n")[0].split()
        )

    def request_kwargs(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        """Build the Converse arguments for one runtime payload."""
        from agentcore_runtime.structured_coach import (
            conversation_for_invoke,
            specialist_system_prompt,
        )

        prior, prompt = conversation_for_invoke(payload)
        current = [{"text": prompt}] if isinstance(prompt, str) else list(prompt)
        return {
            "modelId": self._model_id,
            "system": [{"text": specialist_system_prompt(payload)}],
            "messages": [*prior, {"role": "user", "content": current}],
            "toolConfig": {
                "tools": [
                    {
                        "toolSpec": {
                            "name": "FastChatTurnOutput",
                            "description": self._description,
                            "inputSchema": {"json": self._schema},
                        }
                    }
                ],
                # First-cycle forced tool use, as the runtime middleware sets.
                "toolChoice": {"any": {}},
            },
            "inferenceConfig": {"maxTokens": LIVE_MODEL_MAX_OUTPUT_TOKENS},
        }

    def invoke(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        """Return the runtime wire payload for one fast-chat turn.

        Raises:
            LiveStructuredOutputError: When the reply has no valid tool call.
        """
        from pydantic import ValidationError

        from agentcore_runtime.models import parse_fast_chat_turn_output
        from agentcore_runtime.structured_coach import structured_wire_payload

        self.last_stop_reason = None
        response = self._client.converse(**self.request_kwargs(payload))
        stop_reason = response.get("stopReason")
        self.last_stop_reason = None if stop_reason is None else str(stop_reason)[:40]
        message = ((response.get("output") or {}).get("message")) or {}
        content = message.get("content") or []
        tool_input = None
        for block in content:
            tool_use = block.get("toolUse") if isinstance(block, Mapping) else None
            if isinstance(tool_use, Mapping) and isinstance(tool_use.get("input"), Mapping):
                tool_input = tool_use["input"]
                break
        if tool_input is None:
            raise LiveStructuredOutputError(
                f"no tool call in reply (stopReason={response.get('stopReason')!r})",
                {
                    "kind": "no_tool_call",
                    "stop_reason": self.last_stop_reason,
                    "text_blocks": sum(
                        1 for block in content if isinstance(block, Mapping) and "text" in block
                    ),
                },
            )
        try:
            output = parse_fast_chat_turn_output(dict(tool_input))
        except ValueError as error:
            errors: list[dict[str, Any]] = []
            if isinstance(error, ValidationError):
                # Locations, types and pydantic's static messages only: no input values.
                errors = [
                    {
                        "loc": [str(part) for part in item.get("loc", ())],
                        "type": str(item.get("type") or ""),
                        "msg": str(item.get("msg") or ""),
                    }
                    for item in error.errors(
                        include_url=False, include_context=False, include_input=False
                    )
                ]
            raise LiveStructuredOutputError(
                f"tool input failed validation ({type(error).__name__})",
                {
                    "kind": "tool_input_invalid",
                    "stop_reason": self.last_stop_reason,
                    "errors": errors,
                },
            ) from error
        return structured_wire_payload(output)


def build_live_request(
    row: Mapping[str, Any],
    decision: GateDecision,
    *,
    source_check: bool = True,
    course_titles: Sequence[str] = (),
) -> Any:
    """Build the ``CoachRequest`` production would hand the provider.

    Mirrors the fields ``_prepare_authoritative_turn`` stamps that change the
    first call's prompt. Retrieved excerpts are never attached: a row the gate
    searched for is sent without them (see ``LIVE_MODEL_DEFINITION``).
    ``source_need_check`` is on by default so every row measures the flag;
    ``source_check=False`` sends the turn as production does with
    ``FAST_CHAT_NEEDS_SOURCES_ENABLED`` off (the compare mode's off arm).
    ``course_titles`` are attached only when ``source_check`` is on, as
    production stamps them only on turns with ``source_need_check``.
    """
    from backend.domain import CoachRequest

    selected = list(row["selected_sources"])
    attachments = list(row["attachments"])
    attachment_ids = [f"eval-attachment-{i}" for i, _ in enumerate(attachments, 1)]
    selected_ids = [f"eval-source-{i}" for i, _ in enumerate(selected, 1)]
    if decision.scope_cleared:
        source_ids: list[str] = []
    elif decision.attachment_only:
        source_ids = list(attachment_ids)
    else:
        source_ids = selected_ids + attachment_ids
    return CoachRequest(
        thread_id=f"eval-{row['id']}",
        student_message=str(row["message"]),
        current_stage=str(row["stage"]),
        response_detail="short",
        source_ids=source_ids,
        attachment_source_ids=attachment_ids,
        attachment_titles=[str(item.get("title") or "") for item in attachments],
        allow_model_knowledge=not source_ids and not decision.course,
        history=[
            {"role": turn["role"], "content": turn["text"]} for turn in row["history"]
        ],
        retrieval_required=bool(decision.needs_retrieval),
        source_need_check=bool(source_check),
        course_material_titles=list(course_titles) if source_check else [],
        expected_response_mode=decision.expected_mode,
        mode_policy_intent=decision.intent,
    )


def live_failure_detail(error: BaseException) -> dict[str, Any]:
    """Return safe, structural facts about one failed live call.

    Kinds: ``no_tool_call`` and ``tool_input_invalid`` (from the bridge),
    ``fast_chat_contract`` (the wire adapter's fixed reason token),
    ``contract_rejected`` (``_validated_fast_chat`` category), ``other``
    (for example an AWS error; ``error`` on the row names its class).
    Never message, reply or tool input text.
    """
    from agentcore_runtime.models import FastChatContractError
    from backend.providers import ProviderUnavailableError

    if isinstance(error, LiveStructuredOutputError) and error.detail:
        return dict(error.detail)
    if isinstance(error, FastChatContractError):
        return {"kind": "fast_chat_contract", "reason": str(error.reason)}
    if isinstance(error, ProviderUnavailableError):
        return {"kind": "contract_rejected", "category": str(error.category or "")}
    return {"kind": "other"}


def exception_label(error: BaseException) -> str:
    """Return ``module.Class`` plus the AWS error code when there is one."""
    name = f"{type(error).__module__}.{type(error).__qualname__}"
    code = ""
    response = getattr(error, "response", None)
    if isinstance(response, Mapping) and isinstance(response.get("Error"), Mapping):
        code = str(response["Error"].get("Code") or "")
    return f"{name} (code {code})" if code else name


def is_auth_or_access_error(error: BaseException) -> bool:
    """Return whether *error* is a credential or permission failure."""
    response = getattr(error, "response", None)
    if isinstance(response, Mapping) and isinstance(response.get("Error"), Mapping):
        if str(response["Error"].get("Code") or "") in AUTH_ACCESS_ERROR_CODES:
            return True
    return type(error).__name__ in AUTH_ACCESS_ERROR_CLASSES


def _live_eval_provider() -> Any:
    """Build the provider only to reuse its payload builder (never invoked)."""
    from backend.agentcore_provider import AgentCoreCoachProvider

    class _NoRuntime:
        def invoke_agent_runtime(self, **_kwargs: Any) -> Any:
            raise AssertionError("AgentCore Runtime must not be invoked by the eval")

    return AgentCoreCoachProvider(_EVAL_RUNTIME_ARN, client=_NoRuntime())
