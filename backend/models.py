from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from .settings import settings


@dataclass(frozen=True)
class ModelDefinition:
    id: str
    label: str
    description: str
    group: str
    reasoning_efforts: tuple[str, ...]
    vision: bool = False
    web_search: bool = False
    file_search: bool = False
    image_generation: bool = False
    function_calling: bool = False
    availability: str = "configured"
    deprecated: bool = False

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["reasoning_efforts"] = list(self.reasoning_efforts)
        value["default"] = self.id == settings.default_model
        return value


MODEL_REGISTRY: tuple[ModelDefinition, ...] = (
    ModelDefinition(
        "gpt-5.5",
        "GPT-5.5",
        "Highest-capability model enabled in this application.",
        "Current",
        ("none", "low", "medium", "high", "xhigh"),
        vision=True,
        web_search=True,
        file_search=True,
        image_generation=True,
        function_calling=True,
    ),
    ModelDefinition(
        "gpt-5.4",
        "GPT-5.4",
        "Strong general reasoning and professional work.",
        "Current",
        ("none", "low", "medium", "high", "xhigh"),
        vision=True,
        web_search=True,
        file_search=True,
        image_generation=True,
        function_calling=True,
    ),
    ModelDefinition(
        "gpt-5.4-mini",
        "GPT-5.4 mini",
        "Faster GPT-5.4 option for everyday work.",
        "Current",
        ("none", "low", "medium", "high", "xhigh"),
        vision=True,
        web_search=True,
        file_search=True,
        image_generation=True,
        function_calling=True,
    ),
    ModelDefinition(
        "gpt-5.4-nano",
        "GPT-5.4 nano",
        "Lowest-cost GPT-5.4 option for focused tasks.",
        "Current",
        ("none", "low", "medium", "high", "xhigh"),
        vision=True,
        web_search=True,
        file_search=True,
        image_generation=True,
        function_calling=True,
    ),
    ModelDefinition(
        "gpt-5.3-chat-latest",
        "GPT-5.3 Chat",
        "Requested default. This API model is deprecated and may be removed.",
        "Legacy",
        (),
        vision=True,
        web_search=True,
        file_search=True,
        image_generation=True,
        function_calling=True,
        deprecated=True,
    ),
    ModelDefinition(
        "gpt-5.2",
        "GPT-5.2",
        "Previous frontier reasoning model.",
        "Legacy",
        ("none", "low", "medium", "high", "xhigh"),
        vision=True,
        web_search=True,
        file_search=True,
        image_generation=True,
        function_calling=True,
    ),
    ModelDefinition(
        "gpt-5.1",
        "GPT-5.1",
        "Previous GPT-5 generation for agentic work.",
        "Legacy",
        ("none", "low", "medium", "high"),
        vision=True,
        web_search=True,
        file_search=True,
        image_generation=True,
        function_calling=True,
    ),
    ModelDefinition(
        "gpt-5",
        "GPT-5",
        "Original GPT-5 reasoning model.",
        "Legacy",
        ("minimal", "low", "medium", "high"),
        vision=True,
        web_search=True,
        file_search=True,
        image_generation=True,
        function_calling=True,
    ),
    ModelDefinition(
        "gpt-5-mini",
        "GPT-5 mini",
        "Fast, lower-cost GPT-5 model.",
        "Legacy",
        ("minimal", "low", "medium", "high"),
        vision=True,
        web_search=True,
        file_search=True,
        image_generation=True,
        function_calling=True,
    ),
    ModelDefinition(
        "gpt-5-nano",
        "GPT-5 nano",
        "Fastest original GPT-5 model.",
        "Legacy",
        ("minimal", "low", "medium", "high"),
        vision=True,
        web_search=True,
        file_search=True,
        image_generation=True,
        function_calling=True,
    ),
    ModelDefinition(
        "gpt-4.1",
        "GPT-4.1",
        "Non-reasoning model with strong instruction following.",
        "Legacy",
        (),
        vision=True,
        web_search=True,
        file_search=True,
        function_calling=True,
    ),
    ModelDefinition(
        "gpt-4.1-mini",
        "GPT-4.1 mini",
        "Faster, economical GPT-4.1 model.",
        "Legacy",
        (),
        vision=True,
        web_search=True,
        file_search=True,
        function_calling=True,
    ),
)

MODEL_BY_ID = {model.id: model for model in MODEL_REGISTRY}


def get_model(model_id: str) -> ModelDefinition:
    try:
        return MODEL_BY_ID[model_id]
    except KeyError as exc:
        raise ValueError(f"Model '{model_id}' is not allowed by this application") from exc


def validate_reasoning(model: ModelDefinition, effort: str | None) -> str | None:
    if not model.reasoning_efforts:
        return None
    if effort in model.reasoning_efforts:
        return effort
    return "medium" if "medium" in model.reasoning_efforts else model.reasoning_efforts[0]


def public_model_registry() -> list[dict[str, Any]]:
    return [model.to_dict() for model in MODEL_REGISTRY]
