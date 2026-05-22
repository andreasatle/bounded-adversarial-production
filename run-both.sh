#!/usr/bin/env bash
set -euo pipefail

DOCUMENT_WORKSPACE=".baps-workspace/document-project"
CODING_WORKSPACE=".baps-workspace/coding-project"
LOGROOT=".baps-workspace/logs"
MODEL="gemma4:e4b"
PLANNER_MODEL="gemma4:27b"
mkdir -p "$LOGROOT"

TS=$(date +"%Y%m%d-%H%M%S")
LOGFILE="$LOGROOT/run-both-$TS.log"

rm -rf "$DOCUMENT_WORKSPACE" "$CODING_WORKSPACE"

echo "writing log to: $LOGFILE"

{
  echo "============================================================"
  echo "RUN STARTED: $(date)"
  echo "LOGFILE: $LOGFILE"
  echo "============================================================"
  echo

  echo "============================================================"
  echo "DOCUMENT PROJECT START"
  echo "spec: examples/document-project.yaml"
  echo "workspace: $DOCUMENT_WORKSPACE"
  echo "time: $(date)"
  echo "============================================================"

  BAPS_OLLAMA_MODEL=$MODEL \
  BAPS_OLLAMA_PLANNER_MODEL=$PLANNER_MODEL \
  BAPS_DEBUG=1 \
  uv run baps-run init_and_run \
      --spec examples/document-project.yaml

  echo
  echo "============================================================"
  echo "DOCUMENT PROJECT END"
  echo "time: $(date)"
  echo "============================================================"
  echo

  echo "============================================================"
  echo "CODING PROJECT START"
  echo "spec: examples/coding-project.yaml"
  echo "workspace: $CODING_WORKSPACE"
  echo "time: $(date)"
  echo "============================================================"

  BAPS_OLLAMA_MODEL=$MODEL \
  BAPS_OLLAMA_PLANNER_MODEL=$PLANNER_MODEL \
  BAPS_DEBUG=1 \
  uv run baps-run init_and_run \
      --spec examples/coding-project.yaml

  echo
  echo "============================================================"
  echo "CODING PROJECT END"
  echo "time: $(date)"
  echo "============================================================"
  echo

  echo "============================================================"
  echo "RUN FINISHED: $(date)"
  echo "============================================================"
} >"$LOGFILE" 2>&1

echo "done"
echo "log: $LOGFILE"
tail -50 "$LOGFILE"