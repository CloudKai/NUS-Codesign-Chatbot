"""Offline helpers shared by the ``scripts/evals`` commands.

Nothing here is a command: no module defines ``main`` or a command-line parser,
and none imports a command. The helpers that need AWS, a model or the network
(``live``) only refuse or build requests; they never start a live call on
import. See ``scripts/AGENTS.md`` for what each module owns.
"""
