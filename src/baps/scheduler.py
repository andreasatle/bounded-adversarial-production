from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
from pathlib import Path

from baps.scheduler_policy import ModelConfig, ModelPolicy, compute_reward

_DEFAULT_POLICY_PATH = Path(".baps-workspace/scheduler-policy.json")
_DEFAULT_CONCURRENCY = 1
_DEFAULT_ESCALATION_THRESHOLD = 0.5
_DEFAULT_SPECS = [
    "examples/document-project.yaml",
    "examples/coding-project.yaml",
]


def _default_model_ladder() -> list[ModelConfig]:
    backend = os.getenv("BAPS_BACKEND", "anthropic").lower()
    if backend == "openai":
        return [
            ModelConfig("gpt-4o-mini", "openai", "gpt-4o-mini"),
            ModelConfig("gpt-4o",      "openai", "gpt-4o"),
        ]
    if backend == "ollama":
        model = os.getenv("BAPS_OLLAMA_MODEL", "llama3.2")
        return [ModelConfig("local", "ollama", model)]
    return [
        ModelConfig("haiku",  "anthropic", "claude-haiku-4-5-20251001"),
        ModelConfig("sonnet", "anthropic", "claude-sonnet-4-6"),
        ModelConfig("opus",   "anthropic", "claude-opus-4-7"),
    ]


def _env_for_model(model: ModelConfig) -> dict[str, str]:
    env = os.environ.copy()
    env["BAPS_BACKEND"] = model.backend
    if model.backend == "anthropic":
        env["BAPS_ANTHROPIC_MODEL"] = model.model_id
    elif model.backend == "openai":
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
    proc = await asyncio.create_subprocess_exec(
        "uv", "run", "baps-run", command,
        "--spec", spec,
        "--workspace", str(workspace),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        env=_env_for_model(model),
    )
    stdout, _ = await proc.communicate()
    for line in stdout.decode(errors="replace").splitlines():
        print(f"{prefix} {line}", flush=True)

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


def _print_summary(policy: ModelPolicy) -> None:
    print("\n[scheduler] policy state:")
    for m in policy.models:
        s = policy._stats[m.name]
        print(f"  {m.name:16s}  score={s.score:.3f}  runs={s.runs}")
    print(f"  temperature={policy.temperature:.3f}  total_runs={policy.total_runs}")


def main() -> None:
    from dotenv import load_dotenv
    load_dotenv()

    parser = argparse.ArgumentParser(description="Adaptive baps scheduler.")
    parser.add_argument("specs", nargs="*", help="YAML spec paths (default: examples/*.yaml).")
    parser.add_argument(
        "--concurrency", type=int, default=_DEFAULT_CONCURRENCY,
        help="Max concurrent runs.",
    )
    parser.add_argument(
        "--escalation-threshold", type=float, default=_DEFAULT_ESCALATION_THRESHOLD,
        help="Reward below this triggers escalation to a stronger model.",
    )
    parser.add_argument(
        "--policy", default=str(_DEFAULT_POLICY_PATH),
        help="Path to policy state JSON.",
    )
    args = parser.parse_args()

    specs = args.specs or _DEFAULT_SPECS
    policy_path = Path(args.policy)
    policy_path.parent.mkdir(parents=True, exist_ok=True)

    models = _default_model_ladder()
    policy = ModelPolicy(models)
    policy.load_stats(policy_path)

    print(f"[scheduler] backend={os.getenv('BAPS_BACKEND', 'anthropic')}")
    print(f"[scheduler] ladder={[m.name for m in models]}")
    print(f"[scheduler] concurrency={args.concurrency}  threshold={args.escalation_threshold}")
    print(f"[scheduler] specs={specs}")
    print(f"[scheduler] temperature={policy.temperature:.3f}  total_runs={policy.total_runs}")

    semaphore = asyncio.Semaphore(args.concurrency)

    async def _run_all() -> None:
        await asyncio.gather(*[
            _run_spec(
                spec,
                policy,
                Path(f".baps-workspace/{Path(spec).stem}"),
                semaphore,
                args.escalation_threshold,
                policy_path,
            )
            for spec in specs
        ])

    asyncio.run(_run_all())
    _print_summary(policy)
