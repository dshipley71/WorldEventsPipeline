"""
world_events/orchestrator.py

WorldEventsOrchestrator — manages the MCP stdio session and sequences all
pipeline agents in the correct dependency order.

Jupyter/Colab compatibility:
  ipykernel wraps stdout/stderr in objects that don't support ``fileno()``,
  which MCP's stdio_client requires.  The orchestrator temporarily swaps them
  to ``sys.__stdout__`` / ``sys.__stderr__`` for the duration of the MCP
  session, then restores the originals before printing JSON output.
"""

from __future__ import annotations

import asyncio
import sys
import time
from datetime import timedelta
from typing import List, Optional

from mcp import ClientSession, StdioServerParameters  # type: ignore
from mcp.client.stdio import stdio_client  # type: ignore

from world_events.agents import (
    CrossSourceReviewAgent,
    EventCorrelationAgent,
    GDELTArticleSummaryAgent,
    GDELTReRankAgent,
    MCPEnrichmentAgent,
    NarrativeSynthesisAgent,
    NewsSearchAgent,
    PlottingAgent,
    QueryInputAgent,
    SpikeDetectionAgent,
    StructuredOutputAgent,
    TimelineAnalysisAgent,
)
from world_events.agents.base import BaseAgent
from world_events.logging_utils import log
from world_events.models import PipelineState
from world_events.rate_limiter import AsyncRateLimiter


class WorldEventsOrchestrator:
    """
    Runs the full World-Events pipeline against a named MCP server.

    Parameters
    ----------
    server_command:
        Name (or path) of the MCP server executable.  Defaults to
        ``world-events-mcp`` which must be on ``$PATH``.
    """

    def __init__(self, server_command: str = "world-events-mcp") -> None:
        self.server_command = server_command

    # ── Canonical agent sequence ───────────────────────────────────────────────
    @staticmethod
    def _build_agent_sequence() -> List[BaseAgent]:
        return [
            QueryInputAgent(),
            NewsSearchAgent(),
            TimelineAnalysisAgent(),
            SpikeDetectionAgent(),
            EventCorrelationAgent(),
            GDELTReRankAgent(),           # must precede GDELTArticleSummaryAgent
            GDELTArticleSummaryAgent(),   # runs on post-rerank articles
            MCPEnrichmentAgent(),         # keyword spikes, clusters, entities
            CrossSourceReviewAgent(),
            NarrativeSynthesisAgent(),
            PlottingAgent(),
            StructuredOutputAgent(),
        ]

    async def run_query(
        self,
        query: str,
        gdelt_direct_only: bool = False,
    ) -> Optional[PipelineState]:
        """
        Execute the pipeline for *query*.

        Parameters
        ----------
        query:
            Natural language search string for GDELT and RSS.
        gdelt_direct_only:
            When True, bypass the MCP server for GDELT and use direct HTTP
            calls only (useful for debugging without MCP connectivity).

        Returns
        -------
        PipelineState | None
            Final pipeline state, or None if a fatal error occurred.
        """
        params = StdioServerParameters(command=self.server_command, args=[])

        orig_stdout, orig_stderr = sys.stdout, sys.stderr
        swapped = False
        final_state: Optional[PipelineState] = None

        try:
            # Swap ipykernel wrappers → raw streams so MCP's fileno() calls work
            try:
                sys.stderr.fileno()
            except Exception:
                sys.stderr = sys.__stderr__
                swapped = True
            try:
                sys.stdout.fileno()
            except Exception:
                sys.stdout = sys.__stdout__
                swapped = True

            async with stdio_client(params) as (read_stream, write_stream):
                async with ClientSession(
                    read_stream,
                    write_stream,
                    read_timeout_seconds=timedelta(seconds=180),
                ) as session:
                    await session.initialize()

                    state = PipelineState(query=query)
                    state.params.use_mcp_for_gdelt = not gdelt_direct_only
                    state.gdelt_limiter = AsyncRateLimiter(
                        state.params.gdelt_min_interval_seconds
                    )

                    log(
                        f"Pipeline start query={state.query!r} "
                        f"timespan={state.params.timespan} "
                        f"gdelt_direct_only={gdelt_direct_only} "
                        f"gdelt_limit={state.params.gdelt_limit} "
                        f"rss_limit={state.params.rss_limit} "
                        f"spike_threshold={state.params.spike_threshold} "
                        f"window_days={state.params.window_days} "
                        f"category={state.params.category}"
                    )

                    for agent in self._build_agent_sequence():
                        log(f"Agent start: {agent.name}")
                        t0 = time.time()
                        await agent.run(session, state)
                        dt = time.time() - t0
                        log(
                            f"Agent done: {agent.name} ({dt:.2f}s) "
                            f"timeline_points={len(state.timeline)} "
                            f"spikes={len(state.spikes)} "
                            f"gdelt_articles={len(state.gdelt_articles)} "
                            f"rss_articles={len(state.rss_articles)}"
                        )

                    log("Pipeline complete")
                    final_state = state

        finally:
            if swapped:
                sys.stdout, sys.stderr = orig_stdout, orig_stderr

        # Print JSON output AFTER restoring stdout so it appears in the cell
        if final_state is not None and final_state.output_json:
            print(final_state.output_json)

        return final_state
