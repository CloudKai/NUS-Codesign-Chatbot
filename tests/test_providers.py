"""Provider-selection regression tests that never contact a live model."""

from __future__ import annotations

import pytest

from backend.mock_provider import DeterministicCoachProvider
from backend.providers import ProviderUnavailableError, configured_coach_provider
from backend.settings import settings


def test_configured_provider_uses_deterministic_mock_by_default(monkeypatch):
    """Repository defaults must remain offline and cost-safe."""
    monkeypatch.setattr(settings, "model_provider", "mock")

    assert isinstance(configured_coach_provider(), DeterministicCoachProvider)


def test_removed_provider_value_fails_closed(monkeypatch):
    """A stale private provider value must not silently select another model."""
    monkeypatch.setattr(settings, "model_provider", "retired-provider")

    with pytest.raises(ProviderUnavailableError, match="Unsupported MODEL_PROVIDER"):
        configured_coach_provider()
