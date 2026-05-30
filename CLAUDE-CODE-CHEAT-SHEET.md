# Claude Code Configuration — Cheat Sheet

## Instruction Files — Free text Markdown

| File | Scope |
|---|---|
| `/Library/Application Support/ClaudeCode/CLAUDE.md` (macOS) | Enterprise — org-wide, managed by IT |
| `~/.claude/CLAUDE.md` | Global — your personal preferences, all projects |
| `CLAUDE.md` | Project — shared with team via git |
| `**/**/CLAUDE.md` | Subdirectory — lazily loaded when Claude accesses that dir |
| `.claude/rules/*.md` | Project — same as CLAUDE.md but split across multiple files |

All levels loaded automatically. Hierarchy: enterprise → global → project → subdir.

CLAUDE.md supports imports using @path/to/file syntax:

    See @README for overview and @docs/conventions.md for coding standards.

Auto-memory: Claude can write back to CLAUDE.md automatically as it learns
things (build commands, quirks, decisions). You control whether this is enabled.

---

## Settings Files — JSON

| File | Scope |
|---|---|
| `~/.claude/settings.json` | Global — all projects on this machine |
| `.claude/settings.json` | Project — shared with team via git |
| `.claude/settings.local.json` | Project + personal — gitignored, not shared |

Resolution order: enterprise → global → project → local (local wins on conflict).

Top-level keys in settings.json:

    hooks            Lifecycle automation
    permissions      Allow/deny rules for tools and commands
    model            Model override e.g. "claude-sonnet-4-6"
    mcpServers       MCP server definitions
    env              Environment variables injected into every session
    disableAllHooks  Emergency kill switch — set to true to disable all hooks

Hooks are organized as: event → matcher → handler

Key hook events:

    SessionStart      Fires on startup, resume, /clear, and compact
    PreToolUse        Before any tool call — can block execution
    PostToolUse       After any tool call completes
    UserPromptSubmit  Before Claude processes your prompt — can inject context
    Stop              When Claude finishes responding

Hook handler types:

    command    Run a shell command
    prompt     Send a prompt to a Claude model for evaluation
    agent      Spawn a subagent with tool access to verify conditions
    http       Send an HTTP POST to an endpoint
    mcp_tool   Call a tool on a connected MCP server

---

## Commands — Markdown with optional frontmatter

| Directory | Scope |
|---|---|
| `~/.claude/commands/` | Global — all projects |
| `.claude/commands/` | Project only |

One .md file per command. Filename becomes the slash command name.
Invoked with /filename or /filename argument.

File structure:

    ---
    description: Short description shown in command picker
    argument-hint: Hint shown after /commandname in the picker
    ---

    Prompt text that runs when the command is invoked.
    Use $ARGUMENTS for anything typed after the command name.

---

## Agents — YAML frontmatter + Markdown

| Directory | Scope |
|---|---|
| `~/.claude/agents/` | Global — all projects |
| `.claude/agents/` | Project only |

Specialized subagents Claude can spawn, or that you invoke directly.

File structure:

    ---
    name: agent-name
    description: When and why Claude should use this agent
    model: claude-sonnet-4-6        # optional model override
    tools:                           # optional tool restrictions
      - Read
      - Bash
    hooks:                           # optional hooks scoped to this agent
      Stop:
        - matcher: ""
          hooks:
            - type: command
              command: ./cleanup.sh
    ---

    Agent instructions in free Markdown text.

---

## Skills — YAML frontmatter + Markdown

| Directory | Scope |
|---|---|
| `~/.claude/skills/` | Global — all projects |
| `.claude/skills/` | Project only |

Reusable bundled components — instructions, hooks, and a slash command in one unit.
More powerful than commands: can include their own lifecycle hooks.

File structure:

    ---
    name: skill-name
    description: What this skill does
    hooks:
      PreToolUse:
        - matcher: "Bash"
          hooks:
            - type: command
              command: ./validate.sh
    ---

    Skill instructions in free Markdown text.

---

## Plugins — Plugin bundle

Installed via --plugin-url or from a marketplace.
Each plugin has its own hooks/hooks.json inside the plugin bundle.
Scoped to when the plugin is enabled — not a file you create manually.
Hooks from enabled plugins merge with your user and project hooks.

---

## Summary of entrypoints

| Entrypoint | You create it? | Cascades through subdirs? | Shared via git? |
|---|---|---|---|
| CLAUDE.md | Yes | Yes | Yes (project level) |
| .claude/rules/*.md | Yes | No | Yes |
| settings.json | Yes | No | Yes (project level) |
| settings.local.json | Yes | No | No — gitignore it |
| .claude/commands/ | Yes | No | Yes |
| .claude/agents/ | Yes | No | Yes |
| .claude/skills/ | Yes | No | Yes |
| Plugin hooks | No — installed | No | Via plugin bundle |

---

## Useful commands inside Claude Code

    /hooks        Inspect all active hooks and their source file
    /clear        Wipes context — also triggers SessionStart hooks
    /plan         Claude proposes a plan before executing anything
    /schedule     Create a recurring scheduled task
    /model        Switch model mid-session