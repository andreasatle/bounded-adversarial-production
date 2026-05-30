#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Entity:
    name: str
    kind: str
    path: Path
    line: int
    qualname: str


def iter_entities(path: Path) -> list[Entity]:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)

    entities: list[Entity] = []

    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            entities.append(
                Entity(
                    name=node.name,
                    kind="class",
                    path=path,
                    line=node.lineno,
                    qualname=node.name,
                )
            )

            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    entities.append(
                        Entity(
                            name=item.name,
                            kind="method",
                            path=path,
                            line=item.lineno,
                            qualname=f"{node.name}.{item.name}",
                        )
                    )

        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            entities.append(
                Entity(
                    name=node.name,
                    kind="function",
                    path=path,
                    line=node.lineno,
                    qualname=node.name,
                )
            )

        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = []

            if isinstance(node, ast.Assign):
                targets = list(node.targets)
            else:
                targets = [node.target]

            for target in targets:
                if isinstance(target, ast.Name):
                    entities.append(
                        Entity(
                            name=target.id,
                            kind="variable",
                            path=path,
                            line=node.lineno,
                            qualname=target.id,
                        )
                    )

    return entities


def rg_count(name: str, root: Path) -> tuple[int, str]:
    proc = subprocess.run(
        [
            "rg",
            "--fixed-strings",
            "--line-number",
            "--column",
            "--glob",
            "*.py",
            name,
            str(root),
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    if proc.returncode not in (0, 1):
        raise RuntimeError(proc.stderr)

    output = proc.stdout.strip()
    if not output:
        return 0, ""

    return len(output.splitlines()), output


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--src", default="src/baps")
    parser.add_argument("--tests", default="tests")
    parser.add_argument("--include-tests", action="store_true")
    parser.add_argument("--show-matches", action="store_true")
    parser.add_argument("--min-count", type=int, default=0)
    parser.add_argument("--only-suspicious", action="store_true")
    args = parser.parse_args()

    root = Path(args.root)
    scan_roots = [root / args.src]

    if args.include_tests:
        scan_roots.append(root / args.tests)

    paths: list[Path] = []
    for scan_root in scan_roots:
        if scan_root.exists():
            paths.extend(sorted(scan_root.rglob("*.py")))

    entities: list[Entity] = []
    for path in paths:
        try:
            entities.extend(iter_entities(path))
        except SyntaxError as e:
            print(f"PARSE FAILED: {path}: {e}")

    seen: set[tuple[Path, str, str, int]] = set()
    unique_entities: list[Entity] = []

    for entity in entities:
        key = (entity.path, entity.kind, entity.qualname, entity.line)
        if key not in seen:
            seen.add(key)
            unique_entities.append(entity)

    for entity in unique_entities:
        count, output = rg_count(entity.name, root)

        if count < args.min_count:
            continue

        suspicious = count <= 1

        if args.only_suspicious and not suspicious:
            continue

        marker = "SUSPICIOUS" if suspicious else "OK"

        print("=" * 100)
        print(
            f"{marker} | {entity.kind} | {entity.qualname} | "
            f"{entity.path}:{entity.line} | rg_count={count}"
        )

        if args.show_matches:
            print(output)


if __name__ == "__main__":
    main()