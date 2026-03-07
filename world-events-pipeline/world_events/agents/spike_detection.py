"""
world_events/agents/spike_detection.py

SpikeDetectionAgent — detects statistically significant volume spikes
using a z-score test on the raw GDELT article volume timeline.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, List

from world_events.agents.base import BaseAgent
from world_events.logging_utils import log
from world_events.models import Spike

if TYPE_CHECKING:
    from mcp import ClientSession
    from world_events.models import PipelineState


class SpikeDetectionAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__("SpikeDetectionAgent")

    async def run(self, session: "ClientSession", state: "PipelineState") -> None:  # noqa: ARG002
        vols = [p.raw_volume for p in state.timeline if p.raw_volume is not None]

        if len(vols) < 3:
            state.spikes = []
            log("SpikeDetection: insufficient raw volume points (<3)")
            return

        mean = sum(vols) / len(vols)
        variance = sum((v - mean) ** 2 for v in vols) / max(len(vols) - 1, 1)
        std = math.sqrt(variance) if variance > 0 else 0.0

        if std <= 0:
            state.spikes = []
            log("SpikeDetection: std=0 — no spikes possible")
            return

        spikes: List[Spike] = []
        for p in state.timeline:
            if p.raw_volume is None:
                continue
            z = (p.raw_volume - mean) / std
            if z > state.params.spike_threshold:
                spikes.append(Spike(date=p.date, raw_volume=p.raw_volume, zscore=z))

        state.spikes = spikes
        log(
            f"SpikeDetection complete spikes={len(spikes)} "
            f"threshold_z>{state.params.spike_threshold}"
        )

        if spikes:
            top = sorted(spikes, key=lambda s: s.zscore, reverse=True)[:3]
            log(
                "Top spikes: "
                + ", ".join(
                    f"{s.date.strftime('%Y-%m-%d')} z={s.zscore:.2f} raw={s.raw_volume:.0f}"
                    for s in top
                )
            )
