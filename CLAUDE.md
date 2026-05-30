# CLAUDE.md — baps (bounded-adversarial-production)

## Session Setup — MANDATORY FIRST STEP
Before doing anything else, run:

    uv run python scripts/index_codebase.py

Do not respond to any request until this command has been executed.
Then read CODEBASE_INDEX.md to find relevant index files.
Read only the index files needed for the current task.
All architectural reference comes from the generated indexes — not from this file.
Consult source files only after locating the relevant entities in the index.

## Testing
Run all tests: uv run pytest
Use FakeModelClient for deterministic sequences.
Never couple tests to live model output.
