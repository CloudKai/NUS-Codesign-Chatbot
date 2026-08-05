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


# Default coaching model for new sessions; also kept as LOCKED_* aliases.
DEFAULT_CHAT_MODEL_ID = "gpt-5.6-luna"
DEFAULT_REASONING_EFFORT = "low"
LOCKED_CHAT_MODEL_ID = DEFAULT_CHAT_MODEL_ID
LOCKED_REASONING_EFFORT = DEFAULT_REASONING_EFFORT

MODEL_REGISTRY: tuple[ModelDefinition, ...] = (
    ModelDefinition(
        DEFAULT_CHAT_MODEL_ID,
        "GPT-5.6 Luna",
        "Default coaching model for this application (low reasoning).",
        "Current",
        (DEFAULT_REASONING_EFFORT, "medium"),
        vision=True,
        web_search=True,
        file_search=True,
        image_generation=True,
        function_calling=True,
    ),
)

MODEL_BY_ID = {model.id: model for model in MODEL_REGISTRY}


def get_model(model_id: str) -> ModelDefinition:
    """Return a registered model; unknown IDs fall back to the default."""
    return MODEL_BY_ID.get(model_id) or MODEL_BY_ID[DEFAULT_CHAT_MODEL_ID]


def validate_reasoning(model: ModelDefinition, effort: str | None) -> str | None:
    if not model.reasoning_efforts:
        return None
    if effort in model.reasoning_efforts:
        return effort
    if DEFAULT_REASONING_EFFORT in model.reasoning_efforts:
        return DEFAULT_REASONING_EFFORT
    if "medium" in model.reasoning_efforts:
        return "medium"
    return model.reasoning_efforts[0]


def public_model_registry() -> list[dict[str, Any]]:
    return [model.to_dict() for model in MODEL_REGISTRY]
