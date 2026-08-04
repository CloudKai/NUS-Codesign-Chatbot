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


# Single locked coaching model for this application.
LOCKED_CHAT_MODEL_ID = "gpt-5.6-luna"
LOCKED_REASONING_EFFORT = "low"

MODEL_REGISTRY: tuple[ModelDefinition, ...] = (
    ModelDefinition(
        LOCKED_CHAT_MODEL_ID,
        "GPT-5.6 Luna",
        "Locked coaching model for this application (low reasoning).",
        "Current",
        (LOCKED_REASONING_EFFORT,),
        vision=True,
        web_search=True,
        file_search=True,
        image_generation=True,
        function_calling=True,
    ),
)

MODEL_BY_ID = {model.id: model for model in MODEL_REGISTRY}


def get_model(model_id: str) -> ModelDefinition:
    """Return the locked model; unknown IDs fall back to the only allowed model."""
    return MODEL_BY_ID.get(model_id) or MODEL_BY_ID[LOCKED_CHAT_MODEL_ID]


def validate_reasoning(model: ModelDefinition, effort: str | None) -> str | None:
    if not model.reasoning_efforts:
        return None
    if effort in model.reasoning_efforts:
        return effort
    return model.reasoning_efforts[0]


def public_model_registry() -> list[dict[str, Any]]:
    return [model.to_dict() for model in MODEL_REGISTRY]
