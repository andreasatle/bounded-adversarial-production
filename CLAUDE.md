# CLAUDE.md — baps (bounded-adversarial-production)

## Session Setup
CODEBASE_INDEX.md, CODEBASE_API_*.md and CODEBASE_TEST.md are always current.
Read CODEBASE_INDEX.md first, then only the relevant module index.
Consult source files only after locating entities in the index.

## Ruff (automatic)
A PostToolUse hook runs after every Python file edit:
  uv run ruff check --fix .
  uv run ruff format .
  uv run ruff check .
Do not consider a Python-editing task complete until Ruff passes.
If Ruff reports errors after the hook runs, fix them before finishing.

## Testing
After Ruff passes, run the relevant pytest commands manually for the task.
Run all tests: uv run pytest
Use FakeModelClient for deterministic sequences.
Never couple tests to live model output.

## Simplicity first
If you write 200 lines and it could be 50, rewrite it.
Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

## Surgical changes
Touch only what you must. Don't improve adjacent code, comments, or formatting.
Don't refactor things that aren't broken. Match existing style, even if you'd do it differently.
If you notice unrelated dead code, mention it — don't delete it.

## Clean up your own mess
Remove imports, variables, and functions that YOUR changes made unused.
Don't remove pre-existing dead code unless asked.
Every changed line must trace directly to the user's request.

## Define success criteria
Before coding, state what done looks like.
Loop until the criteria are met and verified.
Weak criteria ("make it work") require constant clarification — be specific.
