"""
world_events/agents/__init__.py

Public API for the agents package.
Import individual agents from here or directly from their modules.
"""

from world_events.agents.base import BaseAgent
from world_events.agents.cross_source_review import CrossSourceReviewAgent
from world_events.agents.event_correlation import EventCorrelationAgent
from world_events.agents.gdelt_rerank import GDELTReRankAgent
from world_events.agents.gdelt_summary import GDELTArticleSummaryAgent
from world_events.agents.mcp_enrichment import MCPEnrichmentAgent
from world_events.agents.narrative_synthesis import NarrativeSynthesisAgent
from world_events.agents.news_search import NewsSearchAgent
from world_events.agents.plotting import PlottingAgent
from world_events.agents.query_input import QueryInputAgent
from world_events.agents.spike_detection import SpikeDetectionAgent
from world_events.agents.structured_output import StructuredOutputAgent
from world_events.agents.timeline_analysis import TimelineAnalysisAgent

__all__ = [
    "BaseAgent",
    "QueryInputAgent",
    "NewsSearchAgent",
    "TimelineAnalysisAgent",
    "SpikeDetectionAgent",
    "EventCorrelationAgent",
    "GDELTReRankAgent",
    "GDELTArticleSummaryAgent",
    "MCPEnrichmentAgent",
    "CrossSourceReviewAgent",
    "NarrativeSynthesisAgent",
    "PlottingAgent",
    "StructuredOutputAgent",
]
