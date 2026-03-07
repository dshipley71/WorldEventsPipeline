"""
world_events/logging_utils.py

Lightweight pipeline logger.
Uses Rich when installed (nice in Colab/Jupyter); falls back to ANSI escapes.
"""

from datetime import datetime, timezone


def log(msg: str) -> None:
    """Emit a timestamped, colour-coded log line."""
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}Z] {msg}"

    # Rich (optional — nicer in Colab)
    try:
        from rich.console import Console  # type: ignore
        from rich.text import Text  # type: ignore

        console = Console()
        style = "cyan"
        low = msg.lower()
        if "error" in low or "failed" in low or "exception" in low:
            style = "bold red"
        elif "warning" in low or "429" in low or "retry" in low:
            style = "yellow"
        elif msg.startswith("Agent start"):
            style = "bold green"
        elif msg.startswith("Agent done") or "complete" in low:
            style = "green"
        elif msg.startswith("Pipeline start"):
            style = "bold magenta"

        console.print(Text(line, style=style))
        return
    except Exception:
        pass

    # ANSI fallback
    low = msg.lower()
    color = "\033[36m"
    if "error" in low or "failed" in low or "exception" in low:
        color = "\033[31;1m"
    elif "warning" in low or "429" in low or "retry" in low:
        color = "\033[33m"
    elif msg.startswith("Agent start"):
        color = "\033[32;1m"
    elif msg.startswith("Agent done") or "complete" in low:
        color = "\033[32m"
    elif msg.startswith("Pipeline start"):
        color = "\033[35;1m"

    print(f"{color}{line}\033[0m", flush=True)
