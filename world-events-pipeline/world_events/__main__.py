"""
world_events/__main__.py

Enables:  python -m world_events "query string"
"""

import asyncio
import sys

from world_events.orchestrator import WorldEventsOrchestrator


async def main() -> None:
    args = sys.argv[1:]
    gdelt_direct_only = "--gdelt-direct-only" in args
    args = [a for a in args if a != "--gdelt-direct-only"]
    query = " ".join(args) if args else "ICE Protests"

    orchestrator = WorldEventsOrchestrator()
    await orchestrator.run_query(query, gdelt_direct_only=gdelt_direct_only)


if __name__ == "__main__":
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        print("Notebook detected — run this in a cell:\n  await main()", file=sys.stderr)
    else:
        asyncio.run(main())
