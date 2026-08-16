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

    invoke = getattr(Agent, "invoke_async", None)
    if invoke is None or not callable(invoke):
        _fail("Agent.invoke_async is missing")
    invoke_sig = inspect.signature(invoke)
    _require_param(invoke_sig, "structured_output_model", "Agent.invoke_async")
    _require_param(invoke_sig, "structured_output_prompt", "Agent.invoke_async")

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
    loader_text = Path(runtime_model.__file__).read_text(encoding="utf-8")
    if "structured_output_prompt" in loader_text:
        _fail("model.py must not set structured_output_prompt on BedrockModel")


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
