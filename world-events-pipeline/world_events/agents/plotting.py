"""
world_events/agents/plotting.py

PlottingAgent — renders a 4-panel intelligence dashboard using Matplotlib:
  1. Volume intensity  (timelinevol)
  2. Raw article count (timelinevolraw)
  3. Tone             (timelinetone)
  4. Spike overlay    (raw volume + detected spike markers)

PNG is saved to disk and base64-encoded for embedding in structured output.
Requires: pip install matplotlib
"""

from __future__ import annotations

import base64
import math
from typing import TYPE_CHECKING, Optional

from world_events.agents.base import BaseAgent
from world_events.logging_utils import log

if TYPE_CHECKING:
    from mcp import ClientSession
    from world_events.models import PipelineState

# Default output path — override via state.params or env if needed
_PLOT_PATH = "/content/timeline_analysis_plots.png"


class PlottingAgent(BaseAgent):
    def __init__(self, output_path: str = _PLOT_PATH) -> None:
        super().__init__("PlottingAgent")
        self.output_path = output_path

    async def run(self, session: "ClientSession", state: "PipelineState") -> None:  # noqa: ARG002
        try:
            import matplotlib.dates as mdates  # type: ignore
            import matplotlib.pyplot as plt  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "Missing dependency: matplotlib. Install with: pip install matplotlib"
            ) from exc

        if not state.timeline:
            log("PlottingAgent: no timeline data — skipping")
            return

        log(
            f"PlottingAgent: rendering dashboard "
            f"timeline_points={len(state.timeline)} spikes={len(state.spikes)}"
        )

        dates = [p.date for p in state.timeline]

        def to_float(x: Optional[float]) -> float:
            if x is None:
                return float("nan")
            try:
                return float(x)
            except Exception:
                return float("nan")

        vol_int_f = [to_float(p.volume_intensity) for p in state.timeline]
        raw_vol_f = [to_float(p.raw_volume) for p in state.timeline]
        tone_f = [to_float(p.tone) for p in state.timeline]

        spike_dates = {s.date for s in state.spikes}

        # Compute mean/std for raw volume threshold line
        raw_clean = [v for v in raw_vol_f if not math.isnan(v)]
        mean_raw = sum(raw_clean) / len(raw_clean) if raw_clean else float("nan")
        std_raw = (
            (sum((v - mean_raw) ** 2 for v in raw_clean) / max(len(raw_clean) - 1, 1)) ** 0.5
            if raw_clean else float("nan")
        )
        threshold_raw = (
            mean_raw + state.params.spike_threshold * std_raw
            if raw_clean and not math.isnan(std_raw)
            else float("nan")
        )

        fig, axes = plt.subplots(4, 1, figsize=(14, 14), sharex=True)
        fig.suptitle(f"Intelligence Dashboard — {state.query}", fontsize=18)

        locator = mdates.AutoDateLocator()
        formatter = mdates.DateFormatter("%b %d")

        def style_ax(ax: object, title: str, ylabel: str) -> None:
            ax.set_title(title, fontsize=13)
            ax.set_ylabel(ylabel, fontsize=11)
            ax.grid(True, linestyle="--", alpha=0.35)
            ax.xaxis.set_major_locator(locator)
            ax.xaxis.set_major_formatter(formatter)

        axes[0].plot(dates, vol_int_f, marker="o", linewidth=2)
        style_ax(axes[0], "Volume Intensity (timelinevol)", "Intensity")

        axes[1].plot(dates, raw_vol_f, marker="o", linewidth=2)
        style_ax(axes[1], "Raw Article Volume (timelinevolraw)", "Count")

        axes[2].plot(dates, tone_f, marker="o", linewidth=2)
        style_ax(axes[2], "Tone (timelinetone)", "Tone")
        axes[2].axhline(0, linewidth=1, alpha=0.5)

        axes[3].plot(dates, raw_vol_f, marker="o", linewidth=2)
        style_ax(axes[3], "Spike Detection Overlay (Raw Volume + Spikes)", "Count")
        if raw_clean and not math.isnan(threshold_raw):
            axes[3].axhline(threshold_raw, linestyle="--", linewidth=2, alpha=0.7)
        spike_x = [d for d in dates if d in spike_dates]
        spike_y = [raw_vol_f[i] for i, d in enumerate(dates) if d in spike_dates]
        if spike_x and spike_y:
            axes[3].scatter(spike_x, spike_y, s=140)

        axes[-1].set_xlabel("Date", fontsize=11)
        for ax in axes:
            for label in ax.get_xticklabels():
                label.set_rotation(45)
                label.set_ha("right")

        plt.tight_layout(rect=[0, 0, 1, 0.96])
        fig.savefig(self.output_path, dpi=160, bbox_inches="tight")
        plt.close(fig)

        state.plot_png_path = self.output_path
        try:
            with open(self.output_path, "rb") as f:
                state.plot_png_base64 = base64.b64encode(f.read()).decode("utf-8")
        except Exception as exc:
            state.plot_png_base64 = None
            log(f"PlottingAgent: failed to base64-encode plot: {exc}")

        state.plot_data = {
            "dates": [d.isoformat() for d in dates],
            "volume_intensity": vol_int_f,
            "raw_volume": raw_vol_f,
            "tone": tone_f,
            "raw_threshold": threshold_raw if (raw_clean and not math.isnan(threshold_raw)) else None,
            "spikes": [
                {"date": s.date.isoformat(), "raw_volume": s.raw_volume, "zscore": s.zscore}
                for s in state.spikes
            ],
        }

        # Display inline when running in Jupyter / Colab
        try:
            from IPython.display import Image, display  # type: ignore
            display(Image(self.output_path))
            print("Saved:", self.output_path)
        except ImportError:
            log(f"PlottingAgent: saved to {self.output_path} (non-Jupyter environment)")

        log("PlottingAgent: dashboard rendered")
