"""
world_events/llm.py

Ollama Cloud client factory and shared LLM helpers.

API key resolution order (first non-empty value wins):
  1. Google Colab Secrets  (OLLAMA_API_KEY)
  2. Environment variable  OLLAMA_API_KEY

Optional env overrides: OLLAMA_HOST, OLLAMA_MODEL
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Optional, Tuple

from world_events.logging_utils import log

if TYPE_CHECKING:
    from world_events.models import PipelineState


def get_ollama_client(state: "PipelineState") -> Optional[Tuple[object, str]]:
    """
    Return ``(client, model_name)`` or ``None`` when LLM is disabled / no key.

    The returned ``client`` is an ``ollama.Client`` instance configured for
    Ollama Cloud.  Callers should treat it as opaque and use ``client.chat()``.
    """
    if not state.params.llm_enabled:
        return None

    api_key = ""

    # 1. Colab Secrets
    try:
        from google.colab import userdata  # type: ignore
        api_key = (userdata.get("OLLAMA_API_KEY") or "").strip()
        if api_key:
            log("LLM: API key loaded from Colab Secrets")
        else:
            log("LLM: Colab secret OLLAMA_API_KEY empty")
    except ImportError:
        pass
    except Exception as exc:
        log(f"LLM: Colab userdata unavailable ({type(exc).__name__}) — trying env var")

    # 2. Environment variable
    if not api_key:
        api_key = os.environ.get("OLLAMA_API_KEY", "").strip()
        if api_key:
            log("LLM: API key loaded from environment variable")

    if not api_key:
        log("LLM: OLLAMA_API_KEY not found — LLM steps will be skipped")
        return None

    host = (
        os.environ.get("OLLAMA_HOST", state.params.llm_host).strip()
        or state.params.llm_host
    )
    model = (
        os.environ.get("OLLAMA_MODEL", state.params.llm_model).strip()
        or state.params.llm_model
    )

    try:
        from ollama import Client  # type: ignore
    except ImportError as e:
        raise RuntimeError(
            "Missing dependency: ollama. Install with: pip install ollama"
        ) from e

    client = Client(host=host, headers={"Authorization": f"Bearer {api_key}"})
    return client, model
