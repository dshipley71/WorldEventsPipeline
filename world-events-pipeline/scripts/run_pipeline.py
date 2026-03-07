#!/usr/bin/env python3
"""
scripts/run_pipeline.py

CLI entry point for the World-Events pipeline.

Usage
-----
  python scripts/run_pipeline.py "ICE Protests"
  python scripts/run_pipeline.py --gdelt-direct-only "Taiwan Strait"
  python scripts/run_pipeline.py --server my-mcp-cmd "South China Sea"

Options
-------
  --gdelt-direct-only   Bypass MCP for GDELT; use direct HTTP calls only.
  --server CMD          Override the MCP server command (default: world-events-mcp).
  --help                Show this message.
"""

import asyncio
import sys
from pathlib import Path

# Allow running from repo root without installing the package
sys.path.insert(0, str(Path(__file__).parent.parent))

from world_events.orchestrator import WorldEventsOrchestrator


def _parse_args():
    args = sys.argv[1:]

    if "--help" in args or "-h" in args:
        print(__doc__)
        sys.exit(0)

    gdelt_direct_only = "--gdelt-direct-only" in args
    args = [a for a in args if a != "--gdelt-direct-only"]

    server = "world-events-mcp"
    if "--server" in args:
        idx = args.index("--server")
        if idx + 1 >= len(args):
            print("Error: --server requires an argument", file=sys.stderr)
            sys.exit(1)
        server = args[idx + 1]
        args = args[:idx] + args[idx + 2:]

    query = " ".join(args).strip() or "ICE Protests"
    return query, gdelt_direct_only, server


async def _run() -> None:
    query, gdelt_direct_only, server = _parse_args()
    orch = WorldEventsOrchestrator(server_command=server)
    await orch.run_query(query, gdelt_direct_only=gdelt_direct_only)


if __name__ == "__main__":
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        # Jupyter / Colab
        print("Notebook mode: run  await _run()  in a cell", file=sys.stderr)
    else:
        asyncio.run(_run())
