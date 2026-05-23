#!/usr/bin/env bash
set -euo pipefail

# Load .env so all BAPS_* and API key variables are available in this shell.
if [[ -f .env ]]; then
  set -o allexport
  source .env
  set +o allexport
fi

DOCUMENT_WORKSPACE=".baps-workspace/document-project"
CODING_WORKSPACE=".baps-workspace/coding-project"
LOGROOT=".baps-workspace/logs"
mkdir -p "$LOGROOT"

TS=$(date +"%Y%m%d-%H%M%S")
LOGFILE="$LOGROOT/run-both-$TS.log"

rm -rf "$DOCUMENT_WORKSPACE" "$CODING_WORKSPACE"

echo "writing log to: $LOGFILE"

{
  echo "============================================================"
  echo "RUN STARTED: $(date)"
  echo "LOGFILE: $LOGFILE"
  echo "BAPS_BACKEND: ${BAPS_BACKEND:-ollama}"
  case "${BAPS_BACKEND:-ollama}" in
    anthropic) echo "MODEL: ${BAPS_ANTHROPIC_MODEL:-claude-sonnet-4-6}" ;;
    openai)    echo "MODEL: ${BAPS_OPENAI_MODEL:-gpt-4o}" ;;
    *)         echo "MODEL: ${BAPS_OLLAMA_MODEL:-llama3.2} (planner: ${BAPS_OLLAMA_PLANNER_MODEL:-unset})" ;;
  esac
  echo "============================================================"
  echo

  echo "============================================================"
  echo "DOCUMENT PROJECT START"
  echo "spec: examples/document-project.yaml"
  echo "workspace: $DOCUMENT_WORKSPACE"
  echo "time: $(date)"
  echo "============================================================"

  BAPS_DEBUG=0 uv run baps-run init_and_run \
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

  BAPS_DEBUG=0 uv run baps-run init_and_run \
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
} 2>&1 | tee "$LOGFILE"

echo "done"
echo "log: $LOGFILE"
