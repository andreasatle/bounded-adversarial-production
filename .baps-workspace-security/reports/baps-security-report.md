## Missing second-layer validation allows empty-body Section to corrupt DocumentArtifact via DeltaDocumentState

Location: state.py — `AppendSectionDelta`, `Section`, and `DocumentArtifact.apply_delta()`

Severity: Medium

Description:
`DocumentArtifact.apply_delta()` is the sole application path for `DeltaDocumentState`. It performs no independent validation of the incoming delta's payload before mutating state. The only validation gate is Pydantic's model construction of `Section`, which enforces non-empty `title` (via `_validate_title`) and non-empty `body` (via `_validate_body`). However, `_validate_body` is defined as:

```python
_validate_body = field_validator("body")(_require_non_empty)
```

where `_require_non_empty` checks `if not value.strip()`. This means a `body` containing only Unicode whitespace (e.g. `"\u2003"` — EM SPACE) passes the strip check, is never flagged, and is silently committed to state. The `apply_delta` method in `DocumentArtifact` unconditionally appends the section tuple without re-validating the constructed `Section` it already holds:

```python
def apply_delta(self, delta: DeltaState) -> DocumentArtifact:
    if isinstance(delta, DeltaDocumentState):
        return DocumentArtifact(
            id=self.id,
            sections=(*self.sections, delta.payload.section),
        )
```

There is no size cap on `body`. An adversarially crafted `DeltaDocumentState` with a multi-megabyte `body` string passes all validators (non-empty, non-whitespace-only) and is appended to `sections` without any length check. The resulting `DocumentArtifact` is written to the `JsonStateStore` verbatim, causing unbounded state growth and potential OOM on future `render_as_text()` calls, which joins all bodies:

```python
def render_as_text(self) -> str:
    return "\n\n".join(section.body for section in self.sections)
```

`StateService.apply_delta()` calls `validate_state_artifacts()` before and after the mutation, but `validate_state_artifacts()` only checks artifact type consistency via the registry — it does not inspect section body sizes or content.

Additionally, `DeltaModifyDocumentState` and `DeltaDeleteDocumentState` branches in `apply_delta` check for title existence but perform no validation on `new_body` beyond what Pydantic already accepted at parse time, meaning a whitespace-unicode-only `new_body` replaces a valid body silently.

Evidence:
```python
# state.py
class Section(BaseModel):
    title: str
    body: str
    source_hash: str | None = None

    _validate_title = field_validator("title")(_require_non_empty)
    _validate_body = field_validator("body")(_require_non_empty)

# _require_non_empty uses value.strip() — passes on Unicode-only whitespace

def apply_delta(self, delta: DeltaState) -> DocumentArtifact:
    if isinstance(delta, DeltaDocumentState):
        return DocumentArtifact(
            id=self.id,
            sections=(*self.sections, delta.payload.section),
        )
```

Recommendation:
1. Add a `_MAX_SECTION_BODY_BYTES` constant (e.g. 65 536 bytes, matching `_MAX_DELTA_BYTES` in `project_adapter.py`) and enforce it inside `_require_non_empty` or a dedicated `Section` validator.
2. Replace `value.strip()` with `value.strip().encode("utf-8")` length check, or use `unicodedata.normalize("NFKC", value).strip()` before the emptiness test so Unicode-only whitespace is rejected.
3. In `DocumentArtifact.apply_delta()`, add an explicit guard that re-checks `len(section.body.encode("utf-8"))` before appending, providing defence-in-depth independent of Pydantic parsing order.

## State Mutation Bypasses in state.py and state_service.py

Location: state.py — `apply_state_delta`, `apply_state_update`, `DocumentArtifact.apply_delta`, `CodingArtifact.apply_delta`; state_service.py — `StateService.apply_delta`, `StateService.apply_update`

Severity: Low

Description:
All State mutation paths were traced. No direct attribute assignment, mutable-reference escape, or backdoor setter was found. Every write to a `State` field flows through `StateService` as required. The following paths were enumerated:

**1. `StateService.apply_delta` (state_service.py)**
Loads state via `self.store.load()`, calls `validate_state_artifacts()`, then `apply_state_delta()`, then `validate_state_artifacts()` again, then `self.store.save()`. No field is mutated in place; all returned objects are freshly constructed Pydantic models.

**2. `StateService.apply_update` (state_service.py)**
Loads state, validates base-state fingerprint via `validate_update_base_state()`, applies `apply_state_update()`, re-validates, then saves. Same immutable pattern.

**3. `apply_state_delta` / `apply_state_update` (state.py)**
Both functions return new `State` instances constructed via `State(artifacts=(...))` — they never mutate the input `State`. `DocumentArtifact.apply_delta` and `CodingArtifact.apply_delta` likewise return new model instances, not mutations of `self`.

**4. Pydantic model immutability**
`State`, `DocumentArtifact`, `CodingArtifact`, `Section`, and `CodeFile` are all Pydantic `BaseModel` subclasses. `StateView` and `ToolCallRecord` carry `ConfigDict(frozen=True)`. The core `State` model does not set `frozen=True`, meaning attribute assignment is not blocked at the Python level. However, no caller in the audited files performs direct attribute assignment (`state.artifacts = ...` or `artifact.sections = ...`). All callers go through `StateService`.

**5. `artifacts` field uses `tuple`, not `list`**
`State.artifacts` is typed `tuple[SerializeAsAny[StateArtifact], ...]` and `DocumentArtifact.sections` is `tuple[Section, ...]`. Tuples are immutable; a caller holding a reference to an existing `State` cannot append to or remove from these containers without constructing a new model.

**6. `JsonStateStore` does not leak mutable references**
`JsonStateStore.load()` deserializes from JSON into a fresh `State` each call. `JsonStateStore.save()` serializes via `state.model_dump(mode="json")` — no shared object reference persists across load/save cycles.

**7. `_get_northstar_from_state` and helper readers (audit_adapter.py, document_adapter.py)**
These functions accept a `State` argument and read from `state.artifacts` without writing. Verified: no assignment to any field.

**Caveat — `State` is not frozen**
Because `State` (and `DocumentArtifact`, `CodingArtifact`) lack `ConfigDict(frozen=True)`, Python does not prevent a caller from writing `state.artifacts = (...)` directly. No such write was found in the audited codebase, but the absence of a runtime guard means a future contributor could introduce a bypass without a type-checker or runtime error stopping them.

Evidence:
```python
# state_service.py
def apply_delta(self, delta: DeltaState) -> State:
    current = self.store.load()
    validated_current = validate_state_artifacts(current, self.registry)
    updated = apply_state_delta(validated_current, delta)
    validated_updated = validate_state_artifacts(updated, self.registry)
    self.store.save(validated_updated)
    return validated_updated

# state.py — tuple fields prevent in-place mutation
class State(BaseModel):
    artifacts: tuple[SerializeAsAny[StateArtifact], ...] = ()
```

Recommendation:
Add `model_config = ConfigDict(frozen=True)` to `State`, `DocumentArtifact`, and `CodingArtifact`. This converts the current convention-only guarantee into an enforced invariant, making direct attribute assignment raise a `ValidationError` at runtime and eliminating the bypass surface for future contributors.

## StateView/State Boundary Violations in state.py, northstar_projection.py, and northstar_apply.py

Location: northstar_projection.py — `StateView`, `NorthStarProjectionRenderer.render()`; document_adapter.py — `build_document_state_view()`; northstar_apply.py — `_apply_proposal()`

Severity: Low

Description:
**1. StateView holds serialized copies, not live State references.**
`StateView` is a frozen Pydantic model (`ConfigDict(frozen=True)`) whose only fields are `id` (str), `projection_type` (enum), `content` (str), `input_fingerprint` (str), and `metadata` (dict). All adapter functions (`build_document_state_view`, `build_coding_state_view`, `build_document_create_game_state_view`) construct `content` by string-joining sanitized artifact fields and `metadata` by calling `section.model_dump(mode="json")` or building plain dicts of scalar values. No direct reference to a `State`, `DocumentArtifact`, or `CodingArtifact` Python object is stored inside `StateView`.

**2. `northstar_projection.py` never receives a `State` object.**
`NorthStarProjectionRenderer.render()` accepts only a `NorthStarProjectionInput`, whose fields are tuples of `NorthStarProjectionItem` (plain Pydantic value objects). The projection path constructs `StateView` entirely from these string fields. There is no code path through which a raw `State` object reaches `render()`.

**3. Sensitive field exposure is limited to what adapters explicitly copy.**
The `metadata` dict in `StateView` for document artifacts contains:
```python
metadata = {
    "target_artifact_id": target_artifact.id,       # str
    "sections": [{"title": s.title, "body": s.body} # scalars only
                 for s in target_artifact.sections],
}
```
No credentials, `source_hash`, internal bookkeeping (`base_state_fingerprint`, artifact registry), or mutable Python objects are included. `Section.source_hash` is present on the model but is never copied into `metadata` or `content` by any adapter.

**4. `northstar_apply.py` never receives a `StateView`.**
`northstar_apply.py` reads proposals from a JSONL file on disk (`northstar_proposals.jsonl`) and writes to `baps-config.json`. It does not import or accept a `StateView` object and has no path back to a live `State` object. The `_apply_proposal` function receives `workspace: Path` and `proposal: dict` only.

**5. `sanitize_model_string` / `sanitize_model_title` applied to content before embedding.**
Adapter functions pass artifact `body` and `title` through `sanitize_model_string` and `sanitize_model_title` before including them in `StateView.content`, stripping prompt-injection patterns. This is defence-in-depth against reflected content from prior model outputs.

**6. No mutable State reference escapes.**
Because `StateView` is frozen and holds only str/dict scalars, a model receiving `StateView.content` cannot obtain a Python reference to the underlying `State`, `DocumentArtifact`, or `CodingArtifact`. Mutation of the state store requires going through `StateService`, which is never accessible from the projection layer.

**One residual gap — unredacted full section bodies in metadata.**
`build_document_state_view` copies complete section `body` strings into `metadata["sections"]`. If a section body contains sensitive operational data (e.g. API keys stored as document content), it would appear in `StateView.metadata` in addition to `StateView.content`. This is an information-density concern, not a reference-leakage bug, and its impact depends on what callers place in document artifact bodies. No credentials were observed in the state schema itself.

Evidence:
```python
# northstar_projection.py — StateView has no State field
class StateView(BaseModel):
    model_config = ConfigDict(frozen=True)
    id: str
    projection_type: ProjectionType
    content: str
    input_fingerprint: str
    metadata: dict = Field(default_factory=dict)

# document_adapter.py — only scalar copies enter metadata
metadata = {
    "target_artifact_id": target_artifact.id,
    "sections": [{"title": s.title, "body": s.body}
                 for s in target_artifact.sections],
}
```

Recommendation:
The boundary is architecturally sound. To close the residual gap, restrict `metadata["sections"]` to titles only (omit `body`) when constructing `StateView` in `build_document_state_view`, keeping full body content only in `content` where it is already sanitized. Add an explicit assertion in `NorthStarProjectionRenderer.render()` confirming the input type is `NorthStarProjectionInput`, guarding against future callers accidentally passing a `State`.

## Prompt Injection via Unvalidated Model Output in run.py, audit_adapter.py, coding_adapter.py, document_adapter.py, and project_adapter.py

Location: run.py (play_game loop, render_blue_prompt / render_red_prompt calls); audit_adapter.py (_render_audit_prompt, render_blue_prompt); coding_adapter.py (render_blue_prompt, _build_coding_prompt); document_adapter.py (build_document_state_view, render_blue_prompt_core); project_adapter.py (sanitize_model_string, normalize_json_candidate, render_blue_prompt_core)

Severity: High

Description:
The system implements a Blue→Red→Referee loop in run.py. Blue (the model) produces a delta JSON string; Red evaluates it; Referee accepts/rejects. Multiple points in this pipeline embed model-generated content into subsequent prompts with insufficient or bypassable sanitization.

**1. run.py — model delta text re-embedded in Red and Referee prompts without re-sanitization**
After Blue produces its raw text response (`blue_response`), `normalize_json_candidate` (project_adapter.py) strips fences and size-checks it, but performs no injection-pattern scrubbing. The parsed delta fields (section titles, bodies, file paths, file content) are then embedded verbatim into the Red prompt via `adapter.render_red_prompt_supplement(state_view, game_spec, delta_state, ...)` and the Referee prompt via `adapter.render_referee_prompt_supplement(...)`. Neither supplement renderer re-applies `sanitize_model_string` to the delta's string fields before embedding them. A Blue model that outputs a section `body` containing `"ignore all previous instructions"` in a context where `normalize_json_candidate` succeeds (the string is non-empty and within 65 536 bytes) will have that text forwarded into the Red and Referee model prompts.

**2. audit_adapter.py — section body from prior Blue turn flows into next Blue prompt via StateView**
`build_document_state_view` (called via the audit adapter's `build_state_view`) renders existing `DocumentArtifact` sections into `StateView.content` using `sanitize_model_string`. However, the audit adapter's `_render_audit_prompt` (visible in the truncated source) embeds `state_view.content` directly into the Blue prompt for the next game turn. If a prior Blue output contained an injection string that narrowly bypassed `_MODEL_INJECTION_RE` (e.g. using Unicode homoglyphs or line-splitting the trigger phrase across a code fence), it survives into the next prompt.

**3. coding_adapter.py — `CodeFile.content` embedded in StateView without sanitization**
`build_coding_create_game_state_view` iterates `target_artifact.files` and calls `sanitize_model_string(line)` on each displayed line. However, `build_coding_state_view` (the play-game path, truncated after line ~873) constructs file content blocks for the StateView. File content written by Blue in a prior turn is `CodeFile.content` — a plain string stored in state with no length cap and no re-sanitization at read time. `sanitize_model_string` is regex-based and covers only the patterns in `_MODEL_INJECTION_RE`; it does not cover all injection vectors (e.g. `"### System:"`, role-switch attempts, or multiline payload split across fence boundaries).

**4. document_adapter.py — `section.body` copied into metadata dict unsanitized**
`build_document_state_view` copies `section.body` into `metadata["sections"]` as a raw string:
```python
metadata = {
    "target_artifact_id": target_artifact.id,
    "sections": [{"title": s.title, "body": s.body}
                 for s in target_artifact.sections],
}
```
`metadata` is not passed through `sanitize_model_string`. If a downstream caller uses `state_view.metadata["sections"][i]["body"]` to construct a prompt (a pattern possible in adapter `render_*` methods), the raw model-generated body is embedded without scrubbing.

**5. project_adapter.py — `normalize_json_candidate` strips fences but not injection strings**
`normalize_json_candidate` enforces a 65 536-byte limit and strips markdown fences, then returns the raw candidate string. This output is passed directly to `json.loads` for delta parsing — correct — but the parsed string *values* (section titles, bodies, file paths) are never passed through `sanitize_model_string` before being stored in state or re-embedded in prompts. The sanitization guard in `sanitize_model_string` is applied only when building prompts in adapters, not universally at parse time.

**Root cause:** The sanitization boundary is inconsistent. `sanitize_model_string` is applied in some prompt-building paths (create-game state view line rendering) but not at the delta parse/store stage, so injection payloads can be round-tripped through state into subsequent prompts even when the first embedding was sanitized.

Evidence:
```python
# project_adapter.py
def normalize_json_candidate(text: str) -> str:
    if len(text.encode("utf-8")) > _MAX_DELTA_BYTES:
        raise ValueError(...)
    normalized = text.strip()
    fence_match = fence_pattern.match(normalized)
    if fence_match is not None:
        normalized = fence_match.group("body").strip()
    return normalized  # no injection scrubbing

# document_adapter.py
metadata = {
    "target_artifact_id": target_artifact.id,
    "sections": [{"title": s.title, "body": s.body}  # raw, unsanitized
                 for s in target_artifact.sections],
}

# coding_adapter.py — build_coding_create_game_state_view
file_lines.extend(sanitize_model_string(line) for line in displayed)
# build_coding_state_view (play-game path) does not show equivalent call
```

Recommendation:
1. Apply `sanitize_model_string` to all string values extracted from a parsed Blue delta (section titles, bodies, file paths, file content) before storing them in state, not only before embedding in prompts. This makes sanitization a write-time invariant rather than a read-time convention.
2. In `render_red_prompt_supplement` and `render_referee_prompt_supplement`, pass delta string fields through `sanitize_model_string` before interpolating into the prompt string.
3. In `build_document_state_view`, apply `sanitize_model_string` to `section.body` when populating `metadata["sections"]`, or omit `body` from metadata entirely.
4. Extend `_MODEL_INJECTION_RE` to cover additional role-switch patterns (e.g. `"^[\t ]*assistant\s*:"`, `"^[\t ]*user\s*:"`) and test against NFKC-normalized input to resist homoglyph splitting.

## Export Path Traversal in run.py, coding_adapter.py, document_adapter.py, and tools.py

Location: coding_adapter.py — `_validate_file_path()` (lines ~37–47), `WriteFileDelta`/`WriteFilesDelta` application path; run.py — `_write_output_files()` / output-dir join (search for `output_dir` / `workspace` path joins); document_adapter.py — no file-write path; tools.py — no file-write path.

Severity: Medium

Description:
**Write sites identified:**

1. **coding_adapter.py — `_validate_file_path()`**
This is the sole pre-write validation gate for file paths originating from Blue delta payloads (`WriteFileDelta.path`, `WriteFilesDelta` batch). It rejects absolute paths and paths containing `..` components:
```python
def _validate_file_path(path: str) -> None:
    if not path or not path.strip():
        raise ValueError("file path must be non-empty")
    p = Path(path)
    if p.is_absolute():
        raise ValueError(...)
    if ".." in p.parts:
        raise ValueError(...)
    if _UNSAFE_PATH_CHARS_RE.search(path):
        raise ValueError(...)
```
After this check the delta path is joined with the output root (the workspace coding artifact directory) and written. **No `Path.resolve()` / `os.path.realpath()` check is performed after the join.** The check `".." in p.parts` operates on the `Path` object's logical parts before any filesystem resolution, so it blocks literal `../` traversal. However, it does not protect against symlink-based escape: if an attacker can first write a file `link` (a valid relative path passing all checks) that is actually a symlink pointing to `../../etc/passwd`, a subsequent write to `link` (or any path whose resolution passes through that symlink) escapes the output root without triggering any validator.

The `_UNSAFE_PATH_CHARS_RE` pattern blocks shell-metacharacter injection (`;&|` etc.) but does not block symlink abuse, which requires no special characters.

2. **run.py — workspace/output directory joins**
`run.py` constructs output paths by joining the workspace root with artifact-relative paths (e.g. for writing `run-result.json`, state files, blackboard entries). These joins use `Path(workspace) / filename` where `filename` values are either hard-coded constants (`"run-result.json"`, `_BLACKBOARD_DIR`, `_NORTHSTAR_PROPOSALS_FILE`) or values read from a config file — not from model-controlled delta fields. No traversal surface was found here; all path components are operator-supplied at launch.

3. **document_adapter.py** — contains no file-write logic. All document artifact mutations are in-memory Pydantic model operations persisted through `JsonStateStore`. No delta path is joined with a filesystem directory. NO FINDING for this file.

4. **tools.py** — contains no file-write logic. `fetch_url` and `web_search` perform outbound HTTP reads only; all output is returned as a string to the caller. NO FINDING for this file.

**Concrete traversal scenario (symlink):**
An attacker controlling Blue output submits:
```json
{"path": "safe_name.py", "content": "malicious"}
```
where `safe_name.py` is pre-planted as a symlink to `../../../../etc/cron.d/backdoor` inside the coding artifact directory. `_validate_file_path("safe_name.py")` passes (relative, no `..`, no unsafe chars). The subsequent `open(output_root / "safe_name.py", "w")` follows the symlink and writes outside the confinement root. No `resolve()`-then-`is_relative_to()` check exists to catch this.

Evidence:
```python
# coding_adapter.py
def _validate_file_path(path: str) -> None:
    p = Path(path)
    if p.is_absolute():
        raise ValueError(...)
    if ".." in p.parts:
        raise ValueError(...)
    if _UNSAFE_PATH_CHARS_RE.search(path):
        raise ValueError(...)
    # ← no Path(output_root / path).resolve().is_relative_to(output_root.resolve())
```

Recommendation:
After joining the validated relative path with the output root, resolve both and assert confinement before opening for write:
```python
resolved = (output_root / path).resolve()
if not resolved.is_relative_to(output_root.resolve()):
    raise ValueError(f"path escapes output root: {path!r}")
```
This is equivalent to the pattern already used correctly in `northstar_apply.py`:
```python
resolved = path.resolve()
if not resolved.is_relative_to(workspace.resolve()):
    raise ValueError(f"config path escapes workspace: {path}")
```
Apply the same pattern to every site in `coding_adapter.py` that opens a file for writing using a Blue-controlled path.

## Delta Parsing Weaknesses in state.py, models.py, and adapter files

Location: state.py — `AppendSectionDelta`, `ModifySectionDelta`, `DeleteSectionDelta`, `WriteFileDelta`, `WriteFilesDelta`; document_adapter.py — `parse_document_delta_json`, `derive_document_state_update_from_delta`; project_adapter.py — `normalize_json_candidate`

Severity: Medium

Description:
**1. Single vs. fragmented parsing boundary.**
There is no single authoritative deserialization boundary. Delta parsing is split across at least three call sites: `normalize_json_candidate` (project_adapter.py) strips fences and enforces a 65 536-byte size cap; `parse_document_delta_json` (document_adapter.py) calls `json.loads` and dispatches on the `"type"` field; and individual Delta models (`AppendSectionDelta`, `ModifySectionDelta`, etc.) are constructed via `model_validate`. None of these three layers cross-checks the others, so a caller that bypasses `normalize_json_candidate` (e.g. by calling `parse_document_delta_json` directly, which is exported) reaches Pydantic validation with no size guard at all.

**2. Type coercion tolerance in Delta payloads.**
Pydantic v2 applies implicit coercion by default. `AppendSectionDelta` wraps a `Section`, whose `body` field is typed `str`. Supplying an integer or list for `body` in the raw JSON causes Pydantic to coerce it to a string (e.g. `42` → `"42"`, `[1,2]` → `"[1, 2]"`), which then passes `_require_non_empty`. The resulting `Section` contains a coerced string that no application code expected. `ModifySectionDelta.new_body` has the same coercion exposure. Neither model sets `model_config = ConfigDict(strict=True)`, which would reject non-string values for `str` fields instead of coercing.

**3. Missing-field tolerance.**
`AppendSectionDelta` sets `model_config = ConfigDict(extra="forbid")`, which blocks unknown fields. However, `Section` itself does not set `extra="forbid"`, so an incoming delta JSON containing `{"section": {"title": "x", "body": "y", "injected_key": "z"}}` silently drops `injected_key` rather than rejecting the payload. While harmless today, this masks malformed inputs that may indicate an adversarial probe.

**4. No range or format checks on string fields.**
`WriteFileDelta.path` and `WriteFilesDelta` batch paths are validated by `_validate_file_path` in coding_adapter.py, but only after deserialization. Between `json.loads` and `_validate_file_path`, the `path` field is an unchecked arbitrary string stored in a `CodeFile` Pydantic model with no length cap. A 10 MB path string passes `json.loads`, passes `CodeFile` construction (only `_require_non_empty` is enforced), and reaches `_validate_file_path` — which checks for `..` and unsafe chars but not length. Storing an arbitrarily long path in state causes unbounded state growth analogous to the `Section.body` issue already documented.

**5. Exploitation scenario.**
An adversarial Blue model outputs:
```json
{"type": "append_section", "section": {"title": "x", "body": 99999}}
```
Pydantic coerces `99999` to `"99999"`, `_require_non_empty` passes, the section is appended. No adapter rejects this. The resulting state is semantically corrupt (a numeric-origin body masquerading as analyst-authored text) but structurally valid, so `validate_state_artifacts` does not flag it.

Evidence:
```python
# state.py
class AppendSectionDelta(BaseModel):
    model_config = ConfigDict(extra="forbid")
    section: Section          # Section has no strict=True, no extra="forbid"

class Section(BaseModel):
    title: str
    body: str                 # coerced from int/list by Pydantic default
    source_hash: str | None = None
    _validate_body = field_validator("body")(_require_non_empty)
    # no length cap, no strict mode

# project_adapter.py
def normalize_json_candidate(text: str) -> str:
    if len(text.encode("utf-8")) > _MAX_DELTA_BYTES:
        raise ValueError(...)
    ...
    return normalized         # size guard absent if caller skips this function
```

Recommendation:
1. Add `model_config = ConfigDict(strict=True)` to `Section`, `AppendSectionDelta`, `ModifySectionDelta`, and `CodeFile` so Pydantic rejects non-string values for `str` fields instead of coercing.
2. Add `extra="forbid"` to `Section` to surface unexpected fields at parse time.
3. Enforce a `_MAX_FIELD_BYTES` length cap inside `Section` and `CodeFile` validators, independent of the upstream `normalize_json_candidate` gate, so the invariant holds even when `parse_document_delta_json` is called directly.