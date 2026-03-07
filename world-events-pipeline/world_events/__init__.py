"""
world_events — World-Events MCP pipeline package.

Quick start
-----------
Jupyter / Colab (in a cell)::

    from world_events.orchestrator import WorldEventsOrchestrator
    orch = WorldEventsOrchestrator()
    await orch.run_query("ICE Protests")

CLI::

    python -m world_events "ICE Protests"
    # or
    python scripts/run_pipeline.py "ICE Protests"
"""

from world_events.config import PipelineParameters
from world_events.models import Article, PipelineState, Spike, TimelinePoint
from world_events.orchestrator import WorldEventsOrchestrator

__all__ = [
    "PipelineParameters",
    "Article",
    "PipelineState",
    "Spike",
    "TimelinePoint",
    "WorldEventsOrchestrator",
]
