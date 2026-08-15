"""Canonical AgentCore coaching runtime for the companion application.

This package is the production ``coach_turn`` harness. It does not import the
companion ``backend`` package. Pytest imports parsing helpers only; it never
invokes AWS or Strands.
"""
