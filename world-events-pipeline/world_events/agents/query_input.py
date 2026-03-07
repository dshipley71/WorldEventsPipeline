"""
world_events/agents/query_input.py

QueryInputAgent — strips and validates the user query before the pipeline runs.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from world_events.agents.base import BaseAgent
from world_events.logging_utils import log

if TYPE_CHECKING:
    from mcp import ClientSession
    from world_events.models import PipelineState


class QueryInputAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__("QueryInputAgent")

    async def run(self, session: "ClientSession", state: "PipelineState") -> None:  # noqa: ARG002
        q = (state.query or "").strip()
        if not q:
            raise ValueError("QueryInputAgent: query must not be empty.")
        state.query = q
        log(f"Query normalised: {state.query!r}")
