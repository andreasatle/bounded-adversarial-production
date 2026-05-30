"""LanguagePlugin implementation for Python: test execution and deterministic structural extraction."""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Sequence

from baps.adapters.project_adapter import VerificationResult

if TYPE_CHECKING:
    from baps.state.state import CodeFile


_CONFTEST_CONTENT = (
    "import sys, os\n"
    'sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))\n'
)

_GITIGNORE_CONTENT = (
    "__pycache__/\n"
    "*.pyc\n"
    "*.pyo\n"
    ".pytest_cache/\n"
    "*.egg-info/\n"
    "dist/\n"
    "build/\n"
    ".venv/\n"
    "uv.lock\n"
)


def _format_function_sig(
    node: ast.FunctionDef | ast.AsyncFunctionDef, indent: str
) -> list[str]:
    """Return lines for a function/method signature + optional docstring first line."""
    result: list[str] = []
    for dec in node.decorator_list:
        result.append(f"{indent}@{ast.unparse(dec)}")
    async_kw = "async " if isinstance(node, ast.AsyncFunctionDef) else ""
    ret = f" -> {ast.unparse(node.returns)}" if node.returns else ""
    result.append(f"{indent}{async_kw}def {node.name}({ast.unparse(node.args)}){ret}:")
    doc = ast.get_docstring(node)
    if doc is not None:
        result.append(f"{indent}    \"\"\"{doc.splitlines()[0].strip()}\"\"\"")
    return result


def _format_class_api(node: ast.ClassDef) -> str:
    """Return API surface for a class: header, docstring, method signatures."""
    lines: list[str] = []
    bases = ", ".join(ast.unparse(b) for b in node.bases)
    lines.append("class " + node.name + (f"({bases})" if bases else "") + ":")
    cls_doc = ast.get_docstring(node)
    if cls_doc is not None:
        lines.append(f'    """{cls_doc.splitlines()[0].strip()}"""')
    for item in node.body:
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
            lines.extend(_format_function_sig(item, indent="    "))
    return "\n".join(lines)


def _parse_pytest_failures(stdout: str) -> list[dict[str, str]]:
    """Parse and return pytest failures."""
    failures = []
    for line in stdout.splitlines():
        if line.startswith("FAILED "):
            rest = line[len("FAILED "):]
            if " - " in rest:
                test_id, reason = rest.split(" - ", 1)
            else:
                test_id, reason = rest, ""
            failures.append({"test_id": test_id.strip(), "reason": reason.strip()})
    return failures


class PythonLanguagePlugin:
    """Represent the PythonLanguagePlugin type."""
    name = "python"
    docker_image = "python:3.12-slim"
    test_command = "pip install pytest -q 2>/dev/null && python -m pytest"

    def initialize(self, project_path: Path) -> bool:
        """Handle initialize."""
        project_path.mkdir(parents=True, exist_ok=True)
        changed = False

        conftest_path = project_path / "conftest.py"
        conftest_before = (
            conftest_path.read_text(encoding="utf-8") if conftest_path.exists() else None
        )
        if conftest_before != _CONFTEST_CONTENT:
            conftest_path.write_text(_CONFTEST_CONTENT, encoding="utf-8")
            changed = True

        gitignore_path = project_path / ".gitignore"
        gitignore_before = (
            gitignore_path.read_text(encoding="utf-8") if gitignore_path.exists() else None
        )
        if gitignore_before != _GITIGNORE_CONTENT:
            gitignore_path.write_text(_GITIGNORE_CONTENT, encoding="utf-8")
            changed = True

        return changed

    def run_tests(self, project_path: Path, sandbox_mode: str) -> VerificationResult:
        """Handle run tests."""
        if sandbox_mode == "none":
            command, completed = self._run_bare(project_path)
        else:
            from baps.tools.sandbox import run_sandboxed
            command, completed = run_sandboxed(
                project_path, sandbox_mode, self.test_command, self.docker_image
            )
        return VerificationResult(
            command=command,
            cwd=str(project_path),
            exit_code=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
            passed=completed.returncode == 0,
        )

    def _run_bare(self, project_path: Path) -> tuple[str, subprocess.CompletedProcess]:
        # Use uv when available; fall back to the current interpreter.
        # test_command is for Docker (needs pip install); bare execution relies
        # on the dev environment having pytest already installed.
        """Handle run bare."""
        try:
            completed = subprocess.run(
                ["uv", "run", "pytest"],
                cwd=project_path, capture_output=True, text=True, check=False,
            )
            return "uv run pytest", completed
        except FileNotFoundError:
            completed = subprocess.run(
                [sys.executable, "-m", "pytest"],
                cwd=project_path, capture_output=True, text=True, check=False,
            )
            return f"{sys.executable} -m pytest", completed

    def build(self, project_path: Path) -> None:
        """Handle build."""
        pass

    def parse_test_failures(self, stdout: str) -> list[dict[str, str]]:
        """Parse and return test failures."""
        return _parse_pytest_failures(stdout)

    def has_tests(self, file_paths: Sequence[str]) -> bool:
        """Return whether the object has tests."""
        return any(
            p.startswith("tests/") or p.startswith("test_")
            for p in file_paths
        )

    def supported_filters(self) -> list[str]:
        """Return supported values for ed filters."""
        return ["api", "tests", "full"]

    def extract_api(self, file: CodeFile) -> str:
        """Extract and return api."""
        try:
            tree = ast.parse(file.content)
        except SyntaxError:
            return file.content

        lines: list[str] = []

        module_doc = ast.get_docstring(tree)
        if module_doc is not None:
            lines.append(f'"""{module_doc.splitlines()[0].strip()}"""')
            lines.append("")

        import_lines = [
            ast.unparse(n) for n in tree.body
            if isinstance(n, (ast.Import, ast.ImportFrom))
        ]
        if import_lines:
            lines.extend(import_lines)
            lines.append("")

        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                bases = ", ".join(ast.unparse(b) for b in node.bases)
                lines.append("class " + node.name + (f"({bases})" if bases else "") + ":")
                cls_doc = ast.get_docstring(node)
                if cls_doc is not None:
                    lines.append(f'    """{cls_doc.splitlines()[0].strip()}"""')
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        lines.extend(_format_function_sig(item, indent="    "))
                lines.append("")
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                lines.extend(_format_function_sig(node, indent=""))
                lines.append("")

        return "\n".join(lines).rstrip()

    def extract_tests(self, file: CodeFile) -> str:
        """Extract and return tests."""
        try:
            tree = ast.parse(file.content)
        except SyntaxError:
            return "Tests:\n  (parse error)"

        entries: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name.startswith("test_"):
                    doc = ast.get_docstring(node)
                    if doc is not None:
                        entries.append(f"  {node.name}: {doc.splitlines()[0].strip()}")
                    else:
                        entries.append(f"  {node.name}")

        if not entries:
            return "Tests:\n  (none)"
        return "Tests:\n" + "\n".join(entries)

    def extract_entity(self, file: CodeFile, entity_id: str, filter: str | None) -> str:
        """Extract and return entity."""
        try:
            tree = ast.parse(file.content)
        except SyntaxError:
            return file.content

        target = None
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                if node.name == entity_id:
                    target = node
                    break

        if target is None:
            available = [
                n.name for n in tree.body
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
            ]
            available_str = ", ".join(f"'{n}'" for n in available) if available else "(none)"
            return f"Entity '{entity_id}' not found. Available entities: {available_str}"

        if filter in (None, "full"):
            src_lines = file.content.splitlines()
            return "\n".join(src_lines[target.lineno - 1:target.end_lineno])

        if filter == "api":
            if isinstance(target, ast.ClassDef):
                return _format_class_api(target)
            return "\n".join(_format_function_sig(target, indent=""))

        return f"Unknown filter '{filter}'. Available filters: {', '.join(self.supported_filters())}"
