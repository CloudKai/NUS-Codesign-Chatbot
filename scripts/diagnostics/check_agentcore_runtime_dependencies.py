"""Network-free AgentCore runtime dependency and Strands API compatibility check.

Install ``agentcore_runtime/requirements.txt`` first. This script does not
call AWS, AgentCore, Bedrock generation, Knowledge Base Retrieve, DSQL, or S3.
It must not invoke Haiku, Sonnet, Luna, or ``specialist_invoke()``.
"""

from __future__ import annotations

import inspect
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any, NoReturn

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

_SYNTHETIC_COACH_TURN = {
    "response_text": "Who is affected at night?",
    "assessment": {
        "current_stage": "problem_identification",
        "contribution_summary": "The student named a street.",
        "stage_assessment": "The contribution is a starting point.",
        "critical_understanding_level": "Developing",
        "confidence": 0.6,
        "recommendation": "stay",
        "recommendation_rationale": "Users are unnamed.",
        "guidance_questions": ["Who is affected at night?"],
        "learning_summary": "The student is locating the problem.",
        "citations": [],
        "facione_scores": {},
    },
    "research_coding": None,
}


def _fail(message: str) -> NoReturn:
    """Print a category-safe error and exit non-zero."""
    print(f"INCOMPATIBLE: {message}", file=sys.stderr)
    raise SystemExit(1)


def _installed(name: str) -> str:
    """Return the installed distribution version or fail closed."""
    try:
        return version(name)
    except PackageNotFoundError:
        _fail(f"{name} is not installed")


def _require_param(signature: inspect.Signature, name: str, owner: str) -> None:
    """Fail when a required callable parameter is missing."""
    if name not in signature.parameters:
        _fail(f"{owner} is missing parameter {name}")


def _check_strands_api() -> dict[str, str]:
    """Inspect installed Strands Agent, AgentResult, and BedrockModel APIs."""
    try:
        from strands import Agent
        from strands.agent.agent_result import AgentResult
        from strands.models import BedrockModel
    except ImportError as error:
        _fail(f"strands import failed: {error.__class__.__name__}")

    agent_init = inspect.signature(Agent.__init__)
    _require_param(agent_init, "tools", "Agent.__init__")
    _require_param(agent_init, "messages", "Agent.__init__")
    _require_param(agent_init, "system_prompt", "Agent.__init__")
    _require_param(agent_init, "retry_strategy", "Agent.__init__")

    invoke = getattr(Agent, "invoke_async", None)
    if invoke is None or not callable(invoke):
        _fail("Agent.invoke_async is missing")
    invoke_sig = inspect.signature(invoke)
    _require_param(invoke_sig, "structured_output_model", "Agent.invoke_async")
    _require_param(invoke_sig, "structured_output_prompt", "Agent.invoke_async")
    _require_param(invoke_sig, "limits", "Agent.invoke_async")

    try:
        from strands import ModelRetryStrategy
    except ImportError:
        try:
            from strands.event_loop._retry import ModelRetryStrategy
        except ImportError as error:
            _fail(f"ModelRetryStrategy import failed: {error.__class__.__name__}")
    retry_init = inspect.signature(ModelRetryStrategy.__init__)
    _require_param(retry_init, "max_attempts", "ModelRetryStrategy.__init__")
    _require_param(retry_init, "initial_delay", "ModelRetryStrategy.__init__")
    _require_param(retry_init, "max_delay", "ModelRetryStrategy.__init__")

    annotations = getattr(AgentResult, "__annotations__", {})
    if "structured_output" not in annotations and not hasattr(AgentResult, "structured_output"):
        _fail("AgentResult.structured_output is missing")

    model_init = inspect.signature(BedrockModel.__init__)
    _require_param(model_init, "region_name", "BedrockModel.__init__")
    config = getattr(BedrockModel, "BedrockConfig", None)
    config_fields = getattr(config, "__annotations__", {}) if config is not None else {}
    required = (
        "model_id",
        "guardrail_id",
        "guardrail_version",
        "guardrail_latest_message",
    )
    missing = [name for name in required if name not in config_fields]
    if missing:
        _fail("BedrockModel.BedrockConfig is missing " + ", ".join(missing))
    if "cache_config" not in config_fields:
        _fail("BedrockModel.BedrockConfig is missing cache_config")
    try:
        from strands.models import CacheConfig
    except ImportError as error:
        _fail(f"CacheConfig import failed: {error.__class__.__name__}")
    cache_init = inspect.signature(CacheConfig.__init__)
    _require_param(cache_init, "strategy", "CacheConfig.__init__")
    return {
        "agent": f"{Agent.__module__}.{Agent.__name__}",
        "agent_result": f"{AgentResult.__module__}.{AgentResult.__name__}",
        "bedrock_model": f"{BedrockModel.__module__}.{BedrockModel.__name__}",
        "cache_config": f"{CacheConfig.__module__}.{CacheConfig.__name__}",
    }


def _check_agentcore_app() -> str:
    """Construct BedrockAgentCoreApp and confirm @app.entrypoint exists."""
    try:
        from bedrock_agentcore import BedrockAgentCoreApp
    except ImportError as error:
        _fail(f"bedrock_agentcore import failed: {error.__class__.__name__}")
    app = BedrockAgentCoreApp()
    entrypoint = getattr(app, "entrypoint", None)
    if entrypoint is None or not callable(entrypoint):
        _fail("BedrockAgentCoreApp.entrypoint is missing")

    @app.entrypoint
    async def invoke(payload: Any, context: Any) -> dict[str, bool]:
        del payload, context
        return {"ok": True}

    del invoke
    return f"{BedrockAgentCoreApp.__module__}.{BedrockAgentCoreApp.__name__}"


def _check_runtime_contracts() -> None:
    """Import runtime models and validate one synthetic CoachTurnOutput."""
    from agentcore_runtime.model import (
        HAIKU_4_5_MODEL_ID,
        PINNED_RUNTIME_PACKAGES,
        SONNET_4_6_MODEL_ID,
        bedrock_model_kwargs,
        load_runtime_requirement_pins,
        runtime_model_config_from_mapping,
    )
    from agentcore_runtime.models import (
        CoachTurnOutput,
        QATurnOutput,
        ReviewTurnOutput,
        RouterOutput,
    )

    pins = load_runtime_requirement_pins()
    if pins != PINNED_RUNTIME_PACKAGES:
        _fail("requirements.txt pins do not match PINNED_RUNTIME_PACKAGES")

    CoachTurnOutput.model_validate(_SYNTHETIC_COACH_TURN)
    QATurnOutput.model_validate(
        {"response_text": "Week 1 covers innovation.", "citations": []}
    )
    ReviewTurnOutput.model_validate(
        {
            "response_text": "Your problem statement is becoming more specific.",
            "strengths": ["Named a place"],
            "areas_to_develop": ["Name who is affected"],
            "synthesis": "Keep locating the users.",
        }
    )
    RouterOutput.model_validate(
        {
            "specialist": "qa",
            "confidence": 0.9,
            "rationale_category": "course_information",
        }
    )

    kwargs = bedrock_model_kwargs(
        runtime_model_config_from_mapping(
            {
                "AGENTCORE_MODEL_PROVIDER": "bedrock",
                "AGENTCORE_MODEL_ID": SONNET_4_6_MODEL_ID,
                "AGENTCORE_MODEL_REGION": "us-west-2",
                "GUARDRAIL_ID": "test-guardrail",
                "GUARDRAIL_VERSION": "1",
            }
        )
    )
    haiku_kwargs = bedrock_model_kwargs(
        runtime_model_config_from_mapping(
            {
                "AGENTCORE_MODEL_PROVIDER": "bedrock",
                "AGENTCORE_MODEL_ID": HAIKU_4_5_MODEL_ID,
                "AGENTCORE_MODEL_REGION": "us-west-2",
                "GUARDRAIL_ID": "test-guardrail",
                "GUARDRAIL_VERSION": "1",
            }
        )
    )
    if haiku_kwargs.get("model_id") != HAIKU_4_5_MODEL_ID:
        _fail("Haiku model_id is not global.anthropic.claude-haiku-4-5-20251001-v1:0")
    if haiku_kwargs.get("guardrail_latest_message") is not True:
        _fail("Haiku guardrail_latest_message is not True")
    if kwargs.get("model_id") != SONNET_4_6_MODEL_ID:
        _fail("Sonnet model_id is not global.anthropic.claude-sonnet-4-6")
    if kwargs.get("region_name") != "us-west-2":
        _fail("Sonnet region_name is not us-west-2")
    if kwargs.get("guardrail_id") != "test-guardrail":
        _fail("guardrail_id was not passed through")
    if kwargs.get("guardrail_version") != "1":
        _fail("guardrail_version was not passed through")
    if kwargs.get("guardrail_latest_message") is not True:
        _fail("guardrail_latest_message is not True")
    if "fallback" in kwargs:
        _fail("model kwargs include a fallback")

    import agentcore_runtime.main as runtime_main
    import agentcore_runtime.model as runtime_model
    import agentcore_runtime.structured_coach as structured_coach

    if not hasattr(runtime_main, "specialist_invoke"):
        _fail("agentcore_runtime.main.specialist_invoke is missing")
    main_text = Path(runtime_main.__file__).read_text(encoding="utf-8")
    if "json.loads(str(" in main_text:
        _fail("main.py still parses str(result) as JSON")
    if not hasattr(structured_coach, "coach_turn_from_agent_result"):
        _fail("structured_coach.coach_turn_from_agent_result is missing")
    repair = getattr(structured_coach, "STRUCTURED_OUTPUT_REPAIR_PROMPT", "")
    if repair != "Please use the output tool now.":
        _fail("STRUCTURED_OUTPUT_REPAIR_PROMPT is missing or incorrect")
    if "structured_output_prompt=STRUCTURED_OUTPUT_REPAIR_PROMPT" not in main_text:
        _fail("main.py does not pass structured_output_prompt on invoke_async")
    if "limits=structured_output_limits_for_role(role)" not in main_text:
        _fail("main.py does not pass role-specific event-loop limits")
    if "retry_strategy" not in main_text:
        _fail("main.py does not pass a ModelRetryStrategy to Agent")
    if getattr(structured_coach, "FAST_CHAT_INVOKE_LIMITS", None) != {"turns": 2}:
        _fail("FAST_CHAT_INVOKE_LIMITS is not turns=2")
    if getattr(structured_coach, "FIRST_CYCLE_STRUCTURED_OUTPUT_TOOL_CHOICE", None) != {
        "any": {}
    }:
        _fail("FIRST_CYCLE_STRUCTURED_OUTPUT_TOOL_CHOICE is not {any: {}}")
    if "apply_first_cycle_tool_choice" not in dir(structured_coach):
        _fail("apply_first_cycle_tool_choice is missing")
    if "record_first_cycle_apply" not in dir(structured_coach):
        _fail("record_first_cycle_apply is missing")
    invoke = main_text.split("async def _structured_role_invoke", 1)[1].split(
        "async def specialist_invoke", 1
    )[0]
    if "_install_first_cycle_structured_output(" not in invoke:
        _fail("main.py does not install first-cycle structured-output middleware")
    if "role=role" not in invoke:
        _fail("first-cycle middleware is not scoped to the invoke role")
    if '"tools": []' not in invoke:
        _fail("Fast Chat Agent construction must pass tools=[]")
    if getattr(structured_coach, "FIRST_CYCLE_FORCE_ROLES", None) != frozenset(
        {"fast_chat"}
    ):
        _fail("FIRST_CYCLE_FORCE_ROLES is not fast_chat-only")
    from inspect import getsource

    if "first_cycle_tool_choice_applied" not in getsource(
        structured_coach.stamp_structured_output_telemetry
    ):
        _fail("stamp_structured_output_telemetry omits first_cycle_tool_choice_applied")

    from strands._middleware.stages import InvokeModelContext, InvokeModelStage
    from strands.tools.structured_output._structured_output_context import (
        StructuredOutputContext,
    )

    if "tool_choice" not in getattr(InvokeModelContext, "__dataclass_fields__", {}):
        _fail("Strands InvokeModelContext has no tool_choice field")
    if not hasattr(InvokeModelStage, "Input"):
        _fail("Strands InvokeModelStage.Input is missing")
    if '{"any": {}}' not in getsource(StructuredOutputContext.set_forced_mode):
        _fail("Strands set_forced_mode default is not {any: {}}")
    if getattr(structured_coach, "DEEP_REVIEW_INVOKE_LIMITS", None) != {"turns": 3}:
        _fail("DEEP_REVIEW_INVOKE_LIMITS is not turns=3")
    haiku_retry = structured_coach.model_retry_policy_for_role("fast_chat")
    if haiku_retry.max_attempts != 2:
        _fail("Fast Chat model retry max_attempts is not 2")
    deep_retry = structured_coach.model_retry_policy_for_role("review_deep")
    if deep_retry.max_attempts != 3:
        _fail("Deep Review model retry max_attempts is not 3")
    loader_text = Path(runtime_model.__file__).read_text(encoding="utf-8")
    if "structured_output_prompt" in loader_text:
        _fail("model.py must not set structured_output_prompt on BedrockModel")
    if "retry_strategy" in loader_text:
        _fail("model.py must not set retry_strategy on BedrockModel")
    if 'retries={"total_max_attempts": 1, "mode": "standard"}' not in loader_text:
        _fail("model.py does not pin botocore Converse retries to one total attempt")


def main() -> int:
    """Run the runtime compatibility diagnostic and print a provenance summary."""
    expected = {
        "strands-agents": _installed("strands-agents"),
        "bedrock-agentcore": _installed("bedrock-agentcore"),
        "pydantic": _installed("pydantic"),
    }
    from agentcore_runtime.model import (
        HAIKU_4_5_MODEL_ID,
        PINNED_RUNTIME_PACKAGES,
        SONNET_4_6_MODEL_ID,
    )

    for name, pinned in PINNED_RUNTIME_PACKAGES.items():
        installed = expected[name]
        if installed != pinned:
            _fail(f"{name} installed {installed} does not match pin {pinned}")

    strands_api = _check_strands_api()
    agentcore_app = _check_agentcore_app()
    _check_runtime_contracts()

    print("agentcore_runtime_dependency_check=ok")
    print(f"python={sys.version.split()[0]}")
    print(f"strands-agents={expected['strands-agents']}")
    print(f"bedrock-agentcore={expected['bedrock-agentcore']}")
    print(f"pydantic={expected['pydantic']}")
    print(f"agent={strands_api['agent']}")
    print(f"agent_result={strands_api['agent_result']}")
    print(f"bedrock_model={strands_api['bedrock_model']}")
    print(f"bedrock_agentcore_app={agentcore_app}")
    print("structured_output_model=present")
    print("structured_output_prompt=present")
    print("invoke_async_limits=present")
    print("agent_retry_strategy=present")
    print("model_retry_strategy=present")
    print("agent_result.structured_output=present")
    print("guardrail_latest_message=present")
    print(f"haiku_model_id={HAIKU_4_5_MODEL_ID}")
    print(f"sonnet_model_id={SONNET_4_6_MODEL_ID}")
    print("implicit_model_fallback=false")
    print("aws_calls=none")
    print("paid_calls=none")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
