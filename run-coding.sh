#!/usr/bin/env bash
set -euo pipefail

WORKSPACE=".baps-workspace/coding-project"
LOGROOT=".baps-workspace/logs/coding-project"

mkdir -p "$LOGROOT"

TS=$(date +"%Y%m%d-%H%M%S")
LOGFILE="$LOGROOT/run-$TS.log"

rm -rf "$WORKSPACE"

echo "writing log to: $LOGFILE"

BAPS_OLLAMA_MODEL=gemma3 \
BAPS_DEBUG=1 \
uv run baps-run init_and_run \
    --spec examples/coding-project.yaml \
    >"$LOGFILE" 2>&1

echo "done"
echo "log: $LOGFILE"
tail -50 "$LOGFILE"