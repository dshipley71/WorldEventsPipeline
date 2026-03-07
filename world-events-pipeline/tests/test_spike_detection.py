"""
tests/test_spike_detection.py

Unit tests for SpikeDetectionAgent — run without MCP or LLM dependencies.
"""

import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from world_events.agents.spike_detection import SpikeDetectionAgent
from world_events.models import PipelineState, TimelinePoint


def _make_state(raw_volumes: list) -> PipelineState:
    state = PipelineState(query="test")
    state.timeline = [
        TimelinePoint(
            date=datetime(2025, 1, i + 1),
            raw_volume=float(v),
        )
        for i, v in enumerate(raw_volumes)
    ]
    return state


@pytest.mark.asyncio
async def test_no_spikes_flat_series():
    state = _make_state([10, 10, 10, 10, 10])
    agent = SpikeDetectionAgent()
    await agent.run(MagicMock(), state)
    assert state.spikes == []


@pytest.mark.asyncio
async def test_spikes_detected():
    # One extreme outlier at index 4
    state = _make_state([10, 11, 10, 9, 100, 10, 11])
    agent = SpikeDetectionAgent()
    await agent.run(MagicMock(), state)
    assert len(state.spikes) >= 1
    assert state.spikes[0].raw_volume == 100.0
    assert state.spikes[0].zscore > 2.0


@pytest.mark.asyncio
async def test_insufficient_data():
    state = _make_state([10, 20])  # fewer than 3 points
    agent = SpikeDetectionAgent()
    await agent.run(MagicMock(), state)
    assert state.spikes == []


@pytest.mark.asyncio
async def test_zero_std():
    state = _make_state([5, 5, 5, 5])
    agent = SpikeDetectionAgent()
    await agent.run(MagicMock(), state)
    assert state.spikes == []


@pytest.mark.asyncio
async def test_custom_threshold():
    state = _make_state([10, 10, 10, 50])
    state.params.spike_threshold = 1.0  # lower threshold
    agent = SpikeDetectionAgent()
    await agent.run(MagicMock(), state)
    assert len(state.spikes) >= 1
