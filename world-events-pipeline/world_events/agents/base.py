"""
world_events/agents/base.py

Abstract BaseAgent — all pipeline agents inherit from this.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcp import ClientSession
    from world_events.models import PipelineState


class BaseAgent:
    """Minimal contract every pipeline agent must implement."""

    def __init__(self, name: str) -> None:
        self.name = name

    async def run(self, session: "ClientSession", state: "PipelineState") -> None:  # noqa: ARG002
        raise NotImplementedError(f"{self.name}.run() not implemented")
