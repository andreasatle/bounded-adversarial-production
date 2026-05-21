### 1. Automatic execution + verification for coding adapters

Current:

```text
coding → export files
```

Target:

```text
coding
→ export
→ run pytest
→ capture result
→ feed result into Red/Referee
```

Without this, coding is still mostly text generation.

---

### 2. Tool boundary / execution contract

Add explicit execution requests:

```text
Blue
    proposes tool request

ToolExecutor
    executes

Result
    returned to game
```

Minimal first tools:

```text
pytest
python file.py
rg
```

Keep tools bounded and typed.

---

### 3. Structured role envelopes

Current role outputs are still fairly ad hoc.

Move toward:

```python
BlueResult
RedFinding
RefereeDecision
ToolRequest
ExecutionResult
```

with provenance.

This helps future blackboard reintroduction.

---

### 4. Contract tests for adapters

You now have:

```text
document
coding
```

Add shared tests:

```text
every adapter:
    init
    CreateGame StateView
    PlayGame StateView
    delta parse
    export
```

Future adapters become easy.

---

### 5. Blackboard reintegration (minimal)

Not old runtime.

Only:

```text
game_start
game_end
tool_exec
state_update
export
```

Append-only.

Never authoritative.

---

### 6. Referee evidence model

Referee should not only say:

```text
accept
reject
revise
```

but:

```text
decision
reason
evidence
missing checks
```

Needed before autonomy increases.

---

### 7. State fingerprints / replay

You already have pieces.

Add:

```text
iteration
state_before
state_after
game
decision
```

Then replay:

```bash
baps replay run-001
```

Huge debugging value.

---

### 8. Tool-aware coding example

Move from:

```text
fibonacci
```

to:

```text
generate code
run pytest
repair
rerun
```

Single closed loop.

This is probably the first *real* autonomous example.

---

### 9. Role provenance

Store:

```text
prompt
response
model
timestamp
game
artifact
```

Needed for audit/debug.

---

### 10. Adapter expansion test

Add third tiny adapter:

```text
todo
note
config
```

Very small.

Purpose:

```text
force generality again
```

---

If I had to pick only **3**:

```text
1. tool execution boundary
2. coding → pytest closed loop
3. minimal blackboard reintegration
```

