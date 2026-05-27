# DRY Audit — baps source code

Audit date: 2026-05-26  
Scope: `src/baps/` and `tests/`  
Method: full file read, line-by-line inspection

---

## Contents

1. [Duplicated Logic](#1-duplicated-logic)
2. [Inconsistent Patterns](#2-inconsistent-patterns)
3. [Structural Violations](#3-structural-violations)
4. [Weakened Tests](#4-weakened-tests)
5. [Dead Code](#5-dead-code)

---

## 1. Duplicated Logic

---

### DL-01 — `_MAX_DELTA_BYTES` constant defined twice — **RESOLVED**

**Severity:** Medium → ~~resolved~~

`normalize_json_candidate` and its duplicate constant were deleted from `project_adapter.py`. `_MAX_DELTA_BYTES` now lives only in `model_output.py`. See DL-03.

---

### DL-02 — `_BLACKBOARD_DIR` constant defined twice

**Severity:** Medium

The string literal `"blackboard"` for the blackboard subdirectory name is defined as a module-level constant in two files.

| Location | Line |
|---|---|
| `src/baps/run.py` | 59 |
| `src/baps/model_output.py` | 38 |

**Impact:** Renaming the blackboard directory requires two edits that can silently diverge.

---

### DL-03 — JSON fence-stripping logic duplicated across `model_output` and `project_adapter` — **RESOLVED**

**Severity:** High → ~~resolved~~

`normalize_json_candidate` deleted from `project_adapter.py`. All fence-stripping now goes through `_extract_json_candidate` in `model_output.py`. The coding adapter's static recovery fallback was also removed. See commit `41997ec`.

---

### DL-04 — `VerificationResult` dict serialization repeated six times — **RESOLVED**

**Severity:** High → ~~resolved~~

`_verification_result_to_dict(result)` extracted to `northstar_projection.py` and imported by all six former call sites. Key ordering is now consistent. See commit `7b25232`.

---

### DL-05 — Verification block string construction duplicated in `_render_red_prompt` and `_render_referee_prompt` — **RESOLVED**

**Severity:** Medium → ~~resolved~~

`_render_verification_block(result, *, guidance)` extracted in `run.py`; called by both `_render_red_prompt` and `_render_referee_prompt` with role-specific guidance text. See commit `7b25232`.

---

### DL-06 — AnthropicClient construction duplicated across `_build_anthropic_client` and `_build_role_client` — **RESOLVED**

**Severity:** High → ~~resolved~~

`_build_anthropic_client` deleted. `_build_role_client` now delegates all construction to `_build_client`. `_build_client` is the single `AnthropicClient` factory. See commit `3fdc7d8`.

---

### DL-07 — OpenAIClient construction duplicated across `_build_openai_client` and `_build_role_client` — **RESOLVED**

**Severity:** High → ~~resolved~~

`_build_openai_client` deleted. `_build_role_client` delegates to `_build_client`. See commit `3fdc7d8`.

---

### DL-08 — `BAPS_BACKENDS` multi-backend parsing block duplicated in two functions

**Severity:** Medium

The entire block that reads `BAPS_BACKENDS`, splits it on commas, validates it is non-empty, builds a client per backend, and wraps in `FallbackClient` is copy-pasted verbatim.

| Location | Lines |
|---|---|
| `src/baps/run.py:_build_model_client` | 427–432 |
| `src/baps/run.py:_build_planner_model_client` | 437–443 |

**Impact:** `_build_planner_model_client` exists only to fall through to a planner-specific Ollama model when the default backend is Ollama; the multi-backend branch is functionally identical. This should be factored into a shared `_build_multi_backend_client()` helper.

---

### DL-09 — `_parse_red_finding_json` and `_parse_referee_decision_json` are structurally identical

**Severity:** Medium

Both functions follow the exact same three-step pattern: `parse_model_output` → check missing required keys → `model_validate` → wrap `ValidationError` in `ValueError`. The only differences are the key sets and the target type.

| Location | Lines |
|---|---|
| `src/baps/run.py:_parse_red_finding_json` | 1249–1265 |
| `src/baps/run.py:_parse_referee_decision_json` | 1268–1284 |

A generic `_parse_role_output(text, all_keys, required_keys, model_cls, context, ...)` would eliminate the duplication without losing clarity.

---

### DL-10 — `_render_red_prompt_supplement_with_adapter` and `_render_referee_prompt_supplement_with_adapter` are structurally identical

**Severity:** Low

Both are optional-method dispatch wrappers with the same five lines of logic: `getattr` → None guard → call with identical keyword arguments.

| Location | Lines |
|---|---|
| `src/baps/run.py:_render_red_prompt_supplement_with_adapter` | 1206–1221 |
| `src/baps/run.py:_render_referee_prompt_supplement_with_adapter` | 1224–1239 |

The only difference is the method name looked up via `getattr`. A single `_call_optional_adapter_method(adapter, method_name, **kwargs)` would cover both.

---

### DL-11 — `_RED_REQUIRED_KEYS` and `_REFEREE_REQUIRED_KEYS` are identical frozensets

**Severity:** Low

Both required-key sets resolve to the same value, `frozenset({"disposition", "rationale"})`, yet are defined as separate constants.

| Location | Line |
|---|---|
| `src/baps/run.py:_RED_REQUIRED_KEYS` | 1243 |
| `src/baps/run.py:_REFEREE_REQUIRED_KEYS` | 1245 |

**Impact:** Any change to what Red and Referee must produce requires two edits. If their requirements ever diverge, this becomes the right separation — until then, a shared constant is appropriate.

---

### DL-12 — `DocumentProjectAdapter.export_state` and `AuditProjectAdapter.export_state` are byte-for-byte identical — **RESOLVED**

**Severity:** High → ~~resolved~~

`export_document_artifact` extracted as a free function in `document_adapter.py`. Both adapters' `export_state` methods now delegate to it as a one-liner. See commit `8e449cc`.

---

### DL-13 — `document_artifact_from_state` and `coding_artifact_from_state` are structural duplicates

**Severity:** Low

Both functions: look up an artifact by ID, raise on not-found, check `isinstance`, raise on wrong type, return the artifact. The only differences are the type checked and the error message.

| Location | Lines |
|---|---|
| `src/baps/document_adapter.py:document_artifact_from_state` | 46–52 |
| `src/baps/coding_adapter.py:coding_artifact_from_state` | 102–108 |

A generic `_get_artifact(state, artifact_id, expected_type, type_name)` in `project_adapter.py` would unify these without sacrificing readability.

---

### DL-14 — StateView SHA-256 fingerprint computation repeated six times

**Severity:** Medium

Every state-view builder computes the same one-liner fingerprint from content, with identical encoding and hex-truncation strategy.

```python
input_fingerprint = hashlib.sha256(content.encode("utf-8")).hexdigest()
```

| Location | Line |
|---|---|
| `src/baps/document_adapter.py:build_document_create_game_state_view` | 99 |
| `src/baps/document_adapter.py:build_document_state_view` | 157 |
| `src/baps/coding_adapter.py:build_coding_create_game_state_view` | 156 |
| `src/baps/coding_adapter.py:build_coding_state_view` | 201 |
| `src/baps/audit_adapter.py:build_audit_create_game_state_view` | 212 |
| `src/baps/audit_adapter.py:build_audit_play_game_state_view` | 268 |

A `_content_fingerprint(content: str) -> str` helper in `northstar_projection.py` or `project_adapter.py` would centralize this.

---

### DL-15 — `=== StateView Start/End ===` delimiter strings appear in every state-view builder

**Severity:** Low

All six state-view builder functions hard-code the same header/footer delimiter strings `"=== StateView Start ==="` and `"=== StateView End ==="`.

| Location | Lines |
|---|---|
| `src/baps/document_adapter.py:build_document_create_game_state_view` | 79, 98 (implied via rstrip) |
| `src/baps/document_adapter.py:build_document_state_view` | 142, 154 |
| `src/baps/coding_adapter.py:build_coding_create_game_state_view` | 136, 153 |
| `src/baps/coding_adapter.py:build_coding_state_view` | 186, 199 |
| `src/baps/audit_adapter.py:build_audit_create_game_state_view` | 191, 210 |
| `src/baps/audit_adapter.py:build_audit_play_game_state_view` | 251, 266 |

Renaming these delimiters (e.g. for model compatibility) requires six edits.

---

### DL-16 — Main output print block duplicated in error and success paths

**Severity:** Low

`main()` prints the same set of key=value fields in both the exception handler and the normal return path. The fields are identical; only the surrounding control flow differs.

| Location | Lines |
|---|---|
| `src/baps/run.py` (error path, inside `except`) | 2424–2441 |
| `src/baps/run.py` (success path) | 2444–2461 |

**Impact:** Adding a new output field requires two edits. A `_print_run_output(...)` helper extracting the common block would eliminate this.

---

### DL-17 — `_require_non_empty` defined twice with different signatures

**Severity:** Low

The concept of "reject an empty string with a helpful error" is implemented independently in two modules.

| Location | Lines | Signature | Notes |
|---|---|---|---|
| `src/baps/state.py` | 23–25 | `(value: str) -> str` | Used as Pydantic `field_validator`; applies NFKC normalization |
| `src/baps/run.py` | 705–708 | `(value: str, field_name: str) -> str` | Used for config validation; no NFKC normalization |

The state.py version is more thorough (normalizes unicode before stripping). The run.py version includes `field_name` in the error message. The two could share a common low-level check.

---

### DL-18 — `_validate_game_spec` reimplements non-empty checks already enforced by Pydantic

**Severity:** Medium

`GameSpec` fields are validated via `_require_non_empty` field validators at construction time (via `state.py`). `_validate_game_spec` in `run.py` manually repeats the same four `.strip()` emptiness checks after `GameSpec.model_validate` has already succeeded.

| Location | Lines |
|---|---|
| `src/baps/run.py:_validate_game_spec` | 1182–1191 |
| `src/baps/state.py:_require_non_empty` (field validator) | 23–25 |

**Impact:** The explicit checks at 1182–1191 add noise without adding safety — any `GameSpec` returned by `model_validate` (run.py:1177) already has non-empty fields. If Pydantic validation ever changes, only one location would be updated.

---

## 2. Inconsistent Patterns

---

### IP-01 — Two separate client-building entry points with different configuration precedence — **RESOLVED**

**Severity:** High → ~~resolved~~

`_build_role_client` now delegates all actual client construction to `_build_client` (no more inline construction). `_build_client_for_role(role, config)` is the active entry point for the canonical spine; `_build_role_client(role)` is the env-only fallback retained for CI/legacy usage. The duplication of construction logic is gone. See commit `3fdc7d8`.

---

### IP-02 — API key validation error messages use four different phrasings

**Severity:** Low

All four check the same condition (`api_key.strip()` is empty) but produce different error text:

| Location | Line | Message |
|---|---|---|
| `src/baps/run.py:_build_anthropic_client` | 406 | `"ANTHROPIC_API_KEY must be set when BAPS_BACKEND=anthropic"` |
| `src/baps/run.py:_build_openai_client` | 417 | `"OPENAI_API_KEY must be set when BAPS_BACKEND=openai"` |
| `src/baps/run.py:_build_role_client` (anthropic) | 490 | `"ANTHROPIC_API_KEY must be set for anthropic backend"` |
| `src/baps/run.py:_build_role_client` (openai) | 499 | `"OPENAI_API_KEY must be set for openai backend"` |
| `src/baps/run.py:_build_client` (anthropic) | 603 | `"ANTHROPIC_API_KEY must be set when using anthropic backend"` |
| `src/baps/run.py:_build_client` (openai) | 611 | `"OPENAI_API_KEY must be set when using openai backend"` |

Six variants total. Users get different messages depending on which code path is hit. The canonical message should live in `_build_client` alone.

---

### IP-03 — `parse_document_delta_json` and `parse_coding_delta_json` differ in how they handle JSON parse failure

**Severity:** Low

Both parsers call `parse_model_output` then check required keys. But their fallback strategies diverge:

| Location | Lines | Fallback on parse failure |
|---|---|---|
| `src/baps/document_adapter.py:parse_document_delta_json` | 218–247 | Raises; no recovery |
| `src/baps/coding_adapter.py:parse_coding_delta_json` | 374–417 | Calls `_recover_malformed_coding_delta_json` on JSON failures only |

The coding adapter's recovery fallback is intentional (the malformed-content problem it solves is coding-specific), but the divergence in error handling makes the two parsers hard to reason about as a pair.

---

## 3. Structural Violations

---

### SV-01 — `DocumentProjectAdapter` and `CodingProjectAdapter` imported but never used in `run.py`

**Severity:** Medium

`run.py` imports both adapter classes directly at the top of the file. In the active execution spine, adapter dispatch goes through `resolve_project_type_adapter` (from `project_adapter.py`), which builds a registry at import time. `DocumentProjectAdapter` and `CodingProjectAdapter` are never referenced in `run.py`'s function bodies.

| Location | Lines |
|---|---|
| `src/baps/run.py` | 30–31 |

CLAUDE.md calls these "compatibility imports... used for tests/legacy references." However, test files import adapters directly from their own modules, not from `run`. These imports exist for no active purpose and add cognitive overhead by implying that `run.py` has a direct dependency on concrete adapter types (a violation of the CLAUDE.md invariant: "run.py is generic").

---

### SV-02 — 15 debug-print functions clog `run.py` and obscure orchestration logic

**Severity:** Medium

Every debug-print function starts with the identical early-return guard and adds no other abstraction. The 15-function block occupies run.py:141–389 — 249 lines before `_build_client_for_backend` even begins.

```python
def _debug_print_XXX(...) -> None:
    if not logger.isEnabledFor(logging.DEBUG):
        return
    logger.debug("XXX:\n%s", ...)
```

| Location | Lines |
|---|---|
| `src/baps/run.py` | 141–389 (all debug-print functions) |

All 15 functions repeat the identical DEBUG guard. They exist solely to avoid running `model_dump` and `_format_debug_yaml_like` when debug logging is disabled. The standard Python logging idiom handles this via `logger.debug("...", *args)` with lazy `%` formatting, or via `if logger.isEnabledFor(logging.DEBUG):` at the call site. These helpers add 249 lines of boilerplate for what amounts to debug plumbing, obscuring the real orchestration logic that follows.

---

### SV-03 — `_build_client` supersedes `_build_anthropic_client`, `_build_openai_client`, and the inner branches of `_build_role_client`, but the older functions remain — **RESOLVED**

**Severity:** Medium → ~~resolved~~

`_build_anthropic_client` and `_build_openai_client` deleted. `_build_role_client` now delegates all client construction to `_build_client`. `_build_client` is the single factory for all three backends. See commit `3fdc7d8`.

---

## 4. Weakened Tests

---

### WT-01 — Two `apply_update` tests assert type but not artifact content

**Severity:** Medium

`test_apply_update_accepts_proposal_without_base_state_fingerprint` and `test_apply_update_accepts_matching_base_state_fingerprint` both apply a `replace_artifact` proposal to `artifact-1` but only assert that a `State` is returned and that the store's `save_calls` incremented. Neither test verifies that `artifact-1` was actually replaced with the new artifact, or that `artifact-2` was left unchanged.

| Location | Lines |
|---|---|
| `tests/test_state_service.py:test_apply_update_accepts_proposal_without_base_state_fingerprint` | 162–179 |
| `tests/test_state_service.py:test_apply_update_accepts_matching_base_state_fingerprint` | 182–201 |

**Example of what is missing:**
```python
# Neither test verifies:
assert updated.artifacts[0].id == "artifact-1"
assert updated.artifacts[0].kind == "document"
assert len(updated.artifacts) == 2  # artifact-2 untouched
```

A `StateService` implementation that saved an empty `State()` or the wrong artifact would pass both tests.

---

### WT-02 — `test_validate_state_loads_and_validates_artifacts_through_registry` asserts call count but not call order

**Severity:** Low

The test asserts `len(calls) == 2` after `validate_state()`. This verifies that two validation calls occurred, but does not assert which artifact was validated first or that both artifact IDs appear in `calls`.

| Location | Lines |
|---|---|
| `tests/test_state_service.py:test_validate_state_loads_and_validates_artifacts_through_registry` | 84–94 |

A registry that validates the same artifact twice (a bug) would still pass `len(calls) == 2`. Stronger assertions:
```python
assert "validate:document:artifact-1" in calls
assert "validate:git_repository:artifact-2" in calls
```

---

### WT-03 — `test_apply_update_loads_validates_applies_validates_saves_and_returns_state` asserts `len(calls) == 3` with no content verification

**Severity:** Low

This test verifies the sequence count of registry adapter calls (3) but does not verify the post-update artifact state. `len(calls) == 3` only checks that one load-validate and one post-apply-validate occurred; it does not verify which artifact was mutated.

| Location | Lines |
|---|---|
| `tests/test_state_service.py:test_apply_update_loads_validates_applies_validates_saves_and_returns_state` | 97–118 |

---

## 5. Dead Code

---

### DC-01 — `DocumentProjectAdapter` import in `run.py` is unused

**Severity:** Low

`DocumentProjectAdapter` is imported at run.py:30 but never referenced in any function body in `run.py`. Adapter resolution in the active code goes through `resolve_project_type_adapter` (via `project_adapter.py`).

| Location | Line |
|---|---|
| `src/baps/run.py` | 30 |

---

### DC-02 — `CodingProjectAdapter` import in `run.py` is unused

**Severity:** Low

Same as DC-01. `CodingProjectAdapter` is imported at run.py:31 and never used.

| Location | Line |
|---|---|
| `src/baps/run.py` | 31 |

---

### DC-03 — `_build_role_client` fallback in `play_game._get_client` is unreachable in the active spine

**Severity:** Low

Inside `play_game`, a closure `_get_client` falls back to `_build_role_client(role)` when `config is None` (run.py:1640). In the canonical execution spine, `play_game` is called from `_solve_gap` (run.py:2142–2150) which always passes `config=config`. The `config is None` branch exists to support legacy call sites that omit `config`, but there are no remaining call sites in the codebase that do so.

| Location | Lines |
|---|---|
| `src/baps/run.py:play_game._get_client` | 1635–1640 |

**Note:** This path is still exercised by some tests that call `play_game` directly without `config`. Removing it would require updating those tests.

---

### DC-04 — `_WORKSPACE_CONFIG_FILE` constant defined but used in only one private function

**Severity:** Low (informational)

The constant `_WORKSPACE_CONFIG_FILE = "baps-config.json"` is defined at run.py:61 and used in a single call to `_workspace_config_path` (run.py:1950). This is not dead code, but the pattern is worth noting as a potential candidate for inlining if the workspace config file is never referenced externally.

| Location | Line |
|---|---|
| `src/baps/run.py:_WORKSPACE_CONFIG_FILE` | 61 |

---

## Summary Table

| ID | Category | Severity | Status | Short Description |
|---|---|---|---|---|
| DL-01 | Duplicate Logic | Medium | ✅ resolved | `_MAX_DELTA_BYTES` defined in two modules |
| DL-02 | Duplicate Logic | Medium | open | `_BLACKBOARD_DIR` defined in two modules (`run.py` and `model_output.py`) |
| DL-03 | Duplicate Logic | High | ✅ resolved | Fence-stripping in `model_output` and `project_adapter` |
| DL-04 | Duplicate Logic | High | ✅ resolved | `VerificationResult` dict serialized at 6 sites |
| DL-05 | Duplicate Logic | Medium | ✅ resolved | Verification block string identical in red and referee prompts |
| DL-06 | Duplicate Logic | High | ✅ resolved | `AnthropicClient` construction duplicated |
| DL-07 | Duplicate Logic | High | ✅ resolved | `OpenAIClient` construction duplicated |
| DL-08 | Duplicate Logic | Medium | open | `BAPS_BACKENDS` parsing block copy-pasted in `_build_model_client` and `_build_planner_model_client` |
| DL-09 | Duplicate Logic | Medium | open | `_parse_red_finding_json` and `_parse_referee_decision_json` are identical in structure |
| DL-10 | Duplicate Logic | Low | open | Two optional-dispatch supplement helpers are identical in structure |
| DL-11 | Duplicate Logic | Low | open | `_RED_REQUIRED_KEYS` and `_REFEREE_REQUIRED_KEYS` are identical frozensets |
| DL-12 | Duplicate Logic | High | ✅ resolved | `export_state` byte-for-byte identical in Document and Audit adapters |
| DL-13 | Duplicate Logic | Low | open | `document_artifact_from_state` and `coding_artifact_from_state` are structural duplicates |
| DL-14 | Duplicate Logic | Medium | open | SHA-256 fingerprint computation repeated in 6 state-view builders |
| DL-15 | Duplicate Logic | Low | open | StateView delimiter strings `=== StateView Start/End ===` hard-coded 6 times |
| DL-16 | Duplicate Logic | Low | open | Main output print block duplicated in error and success paths |
| DL-17 | Duplicate Logic | Low | open | `_require_non_empty` defined in `state.py` and `run.py` independently |
| DL-18 | Duplicate Logic | Medium | open | `_validate_game_spec` reimplements Pydantic-enforced non-empty checks |
| IP-01 | Inconsistent Pattern | High | ✅ resolved | Two client entry points with different config precedence |
| IP-02 | Inconsistent Pattern | Low | open | API key error messages use different phrasings |
| IP-03 | Inconsistent Pattern | Low | open | Document and coding parsers diverge in JSON recovery strategy (intentional) |
| SV-01 | Structural Violation | Medium | open | `DocumentProjectAdapter` and `CodingProjectAdapter` imported but never used in `run.py` |
| SV-02 | Structural Violation | Medium | open | 15 debug-print boilerplate functions clog `run.py` |
| SV-03 | Structural Violation | Medium | ✅ resolved | `_build_client` supersedes earlier builders but they were never removed |
| WT-01 | Weakened Test | Medium | open | Two `apply_update` tests assert type but not artifact content |
| WT-02 | Weakened Test | Low | open | `test_validate_state` asserts call count but not artifact identity |
| WT-03 | Weakened Test | Low | open | `test_apply_update_loads_validates...` asserts count only |
| DC-01 | Dead Code | Low | open | `DocumentProjectAdapter` import in `run.py` unused |
| DC-02 | Dead Code | Low | open | `CodingProjectAdapter` import in `run.py` unused |
| DC-03 | Dead Code | Low | open | `_build_role_client` fallback in `play_game._get_client` unreachable in active spine |
| DC-04 | Dead Code | Low | open | `_WORKSPACE_CONFIG_FILE` only used in one private function (informational) |
