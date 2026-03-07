#!/bin/bash
set -a
source "$(dirname "$0")/.env"
set +a
exec python -m world_event_mcp.dashboard.app
