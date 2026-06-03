from __future__ import annotations

from pathlib import Path
import re


FORBIDDEN_PATTERNS = (
    r'config\["',
    r"config\.get\(",
    r"config: dict\[str, Any\]",
)


def test_main_runtime_path_avoids_dict_style_runtime_config_access() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    target_dirs = (
        repo_root / "src" / "baps" / "core",
        repo_root / "src" / "baps" / "game",
    )
    py_files = [p for target in target_dirs for p in target.rglob("*.py")]

    violations: list[str] = []
    for py_file in py_files:
        text = py_file.read_text(encoding="utf-8")
        rel = py_file.relative_to(repo_root)
        for pattern in FORBIDDEN_PATTERNS:
            for match in re.finditer(pattern, text):
                line = text.count("\n", 0, match.start()) + 1
                violations.append(f"{rel}:{line}: {pattern}")

    assert violations == [], (
        "Found forbidden dict-style runtime config access:\n" + "\n".join(violations)
    )
