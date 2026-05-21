#/bin/bash
rm -rf .baps-workspace/document-project .baps-workspace/coding-project

BAPS_OLLAMA_MODEL=gemma3 uv run baps-run init_and_run --spec examples/document-project.yaml
BAPS_OLLAMA_MODEL=gemma3 uv run baps-run init_and_run --spec examples/coding-project.yaml