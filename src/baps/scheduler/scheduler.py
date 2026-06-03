"""Adaptive scheduler that runs baps specs across a model ladder and updates selection policy scores."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import shutil
from pathlib import Path

from baps.models.models import Backend
from baps.scheduler.scheduler_policy import ModelConfig, ModelPolicy, compute_reward

logger = logging.getLogger(__name__)

_DEFAULT_POLICY_PATH = Path(".baps-workspace/scheduler-policy.json")
_DEFAULT_CONCURRENCY = 1
_DEFAULT_ESCALATION_THRESHOLD = 0.5
_DEFAULT_SPECS = [
    "examples/document-project.yaml",
    "examples/coding-project.yaml",
]

# TODO: Consider making the ladder dynamic during a run:
#   - Reload BAPS_MODEL_LADDER from .env before each spec run
#   - Score-driven escalation: jump to highest-scoring model above threshold
#     rather than stepping through fixed positions
#   - Drop models that score below a floor after N runs
#
# All known models, ordered cheapest/fastest → most capable.
# Referenced by short name in BAPS_MODEL_LADDER.
_KNOWN_MODELS: dict[str, ModelConfig] = {
    # Anthropic
    "haiku": ModelConfig("haiku", Backend.ANTHROPIC, "claude-haiku-4-5-20251001"),
    "sonnet": ModelConfig("sonnet", Backend.ANTHROPIC, "claude-sonnet-4-6"),
    "opus": ModelConfig("opus", Backend.ANTHROPIC, "claude-opus-4-7"),
    # OpenAI
    "gpt-4o-mini": ModelConfig("gpt-4o-mini", Backend.OPENAI, "gpt-4o-mini"),
    "gpt-4o": ModelConfig("gpt-4o", Backend.OPENAI, "gpt-4o"),
    # Ollama (local)
    "deepseek": ModelConfig("deepseek", Backend.OLLAMA, "deepseek-r1:7b"),
    "llama3": ModelConfig("llama3", Backend.OLLAMA, "llama3.1:8b"),
    "qwen-coder": ModelConfig("qwen-coder", Backend.OLLAMA, "qwen2.5-coder:7b"),
    "phi3": ModelConfig("phi3", Backend.OLLAMA, "phi3:14b"),
    "gemma3": ModelConfig("gemma3", Backend.OLLAMA, "gemma3:latest"),
    "gemma4-e4b": ModelConfig("gemma4-e4b", Backend.OLLAMA, "gemma4:e4b"),
    "gemma4-26b": ModelConfig("gemma4-26b", Backend.OLLAMA, "gemma4:26b"),
}

_ANTHROPIC_LADDER = ("haiku", "sonnet", "opus")
_OPENAI_LADDER = ("gpt-4o-mini", "gpt-4o")
_FALLBACK_MODEL = "sonnet"


def _known_model(name: str) -> ModelConfig:
    """Return the ModelConfig for the given short name, raising KeyError if unknown."""
    return _KNOWN_MODELS[name]


def _auto_ladder() -> list[ModelConfig]:
    """Build a ladder from all backends where credentials are present."""
    ladder: list[ModelConfig] = []
    if os.getenv("ANTHROPIC_API_KEY"):
        ladder += [_known_model(name) for name in _ANTHROPIC_LADDER]
    if os.getenv("OPENAI_API_KEY"):
        ladder += [_known_model(name) for name in _OPENAI_LADDER]
    if not ladder:
        ladder.append(_known_model(_FALLBACK_MODEL))
    return ladder


def _default_model_ladder() -> list[ModelConfig]:
    """Read BAPS_MODEL_LADDER (comma-separated names) or fall back to auto-detect."""
    ladder_env = os.getenv("BAPS_MODEL_LADDER", "").strip()
    if not ladder_env:
        return _auto_ladder()
    ladder: list[ModelConfig] = []
    for name in (n.strip() for n in ladder_env.split(",") if n.strip()):
        if name in _KNOWN_MODELS:
            ladder.append(_known_model(name))
        else:
            print(f"[scheduler] warning: unknown model name {name!r} in BAPS_MODEL_LADDER, skipping")
    if not ladder:
        print("[scheduler] warning: BAPS_MODEL_LADDER produced no valid models, using auto-detect")
        return _auto_ladder()
    return ladder


def _env_for_model(model: ModelConfig) -> dict[str, str]:
    """Return a copy of os.environ with BAPS_BACKEND and model-specific env vars set for model."""
    env = os.environ.copy()
    env["BAPS_BACKEND"] = model.backend
    if model.backend == Backend.ANTHROPIC:
        env["BAPS_ANTHROPIC_MODEL"] = model.model_id
    elif model.backend == Backend.OPENAI:
        env["BAPS_OPENAI_MODEL"] = model.model_id
    else:
        env["BAPS_OLLAMA_MODEL"] = model.model_id
    return env


async def _run_baps(
    spec: str,
    model: ModelConfig,
    workspace: Path,
    command: str,
    prefix: str,
) -> dict:
    """Run baps-run asynchronously for the given spec and model, returning the run-result dict."""
    proc = await asyncio.create_subprocess_exec(
        "uv",
        "run",
        "baps-run",
        command,
        "--spec",
        spec,
        "--workspace",
        str(workspace),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        env=_env_for_model(model),
    )
    assert proc.stdout is not None
    async for raw in proc.stdout:
        print(f"{prefix} {raw.decode(errors='replace').rstrip()}", flush=True)
    await proc.wait()

    result_path = workspace / "run-result.json"
    if result_path.exists():
        try:
            return json.loads(result_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return {"stop_reason": "unknown", "verification_passed": None}


async def _run_spec(
    spec: str,
    policy: ModelPolicy,
    workspace: Path,
    semaphore: asyncio.Semaphore,
    escalation_threshold: float,
    policy_path: Path,
) -> None:
    """Run a single spec through the adaptive escalation loop, updating and saving the policy."""
    async with semaphore:
        spec_name = Path(spec).stem
        prefix = f"[{spec_name}]"

        if workspace.exists():
            shutil.rmtree(workspace)

        model = policy.select()
        command = "init_and_run"

        while True:
            print(f"{prefix} model={model.name} ({model.model_id})", flush=True)
            result = await _run_baps(spec, model, workspace, command, prefix)
            reward = compute_reward(result)
            print(
                f"{prefix} stop_reason={result.get('stop_reason')}  "
                f"verification_passed={result.get('verification_passed')}  "
                f"reward={reward:.2f}",
                flush=True,
            )
            policy.update(model.name, reward)
            policy.save(policy_path)

            if reward >= escalation_threshold:
                break

            next_model = policy.escalate_from(model)
            if next_model is None:
                print(f"{prefix} ladder exhausted at {model.name}", flush=True)
                break

            print(f"{prefix} escalating {model.name} → {next_model.name}", flush=True)
            model = next_model
            command = "run"


_SCORE_FLOOR = 0.2  # models scoring below this after min_runs are dropped from the ladder
_FLOOR_MIN_RUNS = 5  # minimum runs before a model is eligible for floor-dropping


def _drop_underperformers(policy: ModelPolicy) -> list[str]:
    """Remove models that score below the floor after enough runs. Returns names of dropped models."""
    dropped = []
    survivors = []
    for m in policy.models:
        s = policy._stats[m.name]
        if s.runs >= _FLOOR_MIN_RUNS and s.score < _SCORE_FLOOR:
            dropped.append(m.name)
        else:
            survivors.append(m)
    if dropped and len(survivors) > 0:
        policy.models = survivors
    return dropped if len(survivors) > 0 else []


def _print_summary(policy: ModelPolicy) -> None:
    """Log a human-readable summary of current model scores and policy temperature."""
    lines = ["[scheduler] policy state:"]
    for m in policy.models:
        s = policy._stats[m.name]
        lines.append(f"  {m.name:16s}  score={s.score:.3f}  runs={s.runs}")
    lines.append(f"  temperature={policy.temperature:.3f}  total_runs={policy.total_runs}")
    logger.info("\n".join(lines))


def main() -> None:
    """CLI entry point for the adaptive baps scheduler: run specs across a model ladder for N rounds."""
    from dotenv import load_dotenv

    load_dotenv()
    _log_level = getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO)
    logging.basicConfig(
        level=_log_level,
        format="%(asctime)s %(levelname)-5s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    parser = argparse.ArgumentParser(description="Adaptive baps scheduler.")
    parser.add_argument("specs", nargs="*", help="YAML spec paths (default: examples/*.yaml).")
    parser.add_argument(
        "--concurrency",
        type=int,
        default=_DEFAULT_CONCURRENCY,
        help="Max concurrent runs.",
    )
    parser.add_argument(
        "--escalation-threshold",
        type=float,
        default=_DEFAULT_ESCALATION_THRESHOLD,
        help="Reward below this triggers escalation to a stronger model.",
    )
    parser.add_argument(
        "--policy",
        default=str(_DEFAULT_POLICY_PATH),
        help="Path to policy state JSON.",
    )
    parser.add_argument(
        "--rounds",
        type=int,
        default=1,
        help="Number of rounds to run each spec (reloads ladder from BAPS_MODEL_LADDER each round).",
    )
    args = parser.parse_args()

    specs = args.specs or _DEFAULT_SPECS
    policy_path = Path(args.policy).resolve()
    if not policy_path.is_relative_to(Path.cwd().resolve()):
        import sys as _sys

        logger.error(
            "[scheduler] --policy path must be within the current directory: %s",
            policy_path,
        )
        _sys.exit(1)
    policy_path.parent.mkdir(parents=True, exist_ok=True)

    models = _default_model_ladder()
    policy = ModelPolicy(models)
    policy.load_stats(policy_path)

    logger.info("[scheduler] backend=%s", os.getenv("BAPS_BACKEND", "ollama"))
    logger.info("[scheduler] ladder=%s", [m.name for m in models])
    logger.info(
        "[scheduler] concurrency=%d  threshold=%s  rounds=%d",
        args.concurrency,
        args.escalation_threshold,
        args.rounds,
    )
    logger.info("[scheduler] specs=%s", specs)
    logger.info(
        "[scheduler] temperature=%.3f  total_runs=%d",
        policy.temperature,
        policy.total_runs,
    )

    semaphore = asyncio.Semaphore(args.concurrency)

    for round_num in range(1, args.rounds + 1):
        if args.rounds > 1:
            # Reload ladder from env — allows live tuning of BAPS_MODEL_LADDER between rounds.
            # Re-create policy from the new ladder, then restore persisted scores.
            models = _default_model_ladder()
            policy = ModelPolicy(models)
            policy.load_stats(policy_path)
            print(f"\n[scheduler] round {round_num}/{args.rounds}  ladder={[m.name for m in policy.models]}")
        else:
            print(f"\n[scheduler] round 1/1  ladder={[m.name for m in policy.models]}")

        async def _run_all() -> None:
            await asyncio.gather(
                *[
                    _run_spec(
                        spec,
                        policy,
                        Path(f".baps-workspace/{Path(spec).stem}"),
                        semaphore,
                        args.escalation_threshold,
                        policy_path,
                    )
                    for spec in specs
                ]
            )

        asyncio.run(_run_all())

        dropped = _drop_underperformers(policy)
        if dropped:
            print(f"[scheduler] dropped underperforming models: {dropped}")
            policy.save(policy_path)

    _print_summary(policy)
