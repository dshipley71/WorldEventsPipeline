"""
world_events/agents/narrative_synthesis.py

NarrativeSynthesisAgent — produces a concise human-readable summary and
a simple risk label (low / moderate / high) based on spike count.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from world_events.agents.base import BaseAgent
from world_events.logging_utils import log

if TYPE_CHECKING:
    from mcp import ClientSession
    from world_events.models import PipelineState


class NarrativeSynthesisAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__("NarrativeSynthesisAgent")

    async def run(self, session: "ClientSession", state: "PipelineState") -> None:  # noqa: ARG002
        spike_count = len(state.spikes)
        gdelt_count = len(state.gdelt_articles)
        rss_count = len(state.rss_articles)

        state.analysis_summary = (
            f"Query: {state.query}  |  "
            f"Detected {spike_count} spike(s).  |  "
            f"Correlated {gdelt_count} GDELT and {rss_count} RSS articles."
        )

        if spike_count == 0:
            state.risk_assessment = "low"
        elif spike_count <= 2:
            state.risk_assessment = "moderate"
        else:
            state.risk_assessment = "high"

        log(f"NarrativeSynthesis complete risk={state.risk_assessment}")
