from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Sequence

from baps.adapters.project_adapter import VerificationResult


_BUILD_ZIG_CONTENT = """\
const std = @import("std");

pub fn build(b: *std.Build) void {
    const target = b.standardTargetOptions(.{});
    const optimize = b.standardOptimizeOption(.{});

    const lib = b.addStaticLibrary(.{
        .name = "project",
        .root_source_file = b.path("src/main.zig"),
        .target = target,
        .optimize = optimize,
    });
    b.installArtifact(lib);

    const main_tests = b.addTest(.{
        .root_source_file = b.path("src/main.zig"),
        .target = target,
        .optimize = optimize,
    });
    const run_main_tests = b.addRunArtifact(main_tests);
    const test_step = b.step("test", "Run tests");
    test_step.dependOn(&run_main_tests.step);
}
"""

_MAIN_ZIG_CONTENT = """\
const std = @import("std");

pub fn main() !void {}

test "placeholder" {
    // TODO: implement
}
"""

_GITIGNORE_CONTENT = (
    ".zig-cache/\n"
    "zig-out/\n"
)


class ZigLanguagePlugin:
    name = "zig"
    docker_image = "baps-zig:latest"
    test_command = "zig build test"

    def initialize(self, project_path: Path) -> bool:
        project_path.mkdir(parents=True, exist_ok=True)
        changed = False

        build_zig = project_path / "build.zig"
        if not build_zig.exists():
            build_zig.write_text(_BUILD_ZIG_CONTENT, encoding="utf-8")
            changed = True

        src_dir = project_path / "src"
        src_dir.mkdir(exist_ok=True)
        main_zig = src_dir / "main.zig"
        if not main_zig.exists():
            main_zig.write_text(_MAIN_ZIG_CONTENT, encoding="utf-8")
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
        completed = subprocess.run(
            ["zig", "build", "test"],
            cwd=project_path, capture_output=True, text=True, check=False,
        )
        return "zig build test", completed

    def build(self, project_path: Path) -> None:
        pass

    def parse_test_failures(self, stdout: str) -> list[dict[str, str]]:
        failures = []
        for line in stdout.splitlines():
            if line.startswith("FAIL "):
                rest = line[len("FAIL "):]
                failures.append({"test_id": rest.strip(), "reason": ""})
            elif line.startswith("error: ") and ":test." in line:
                failures.append({"test_id": line.strip(), "reason": ""})
        return failures

    def has_tests(self, file_paths: Sequence[str]) -> bool:
        return any(p.endswith(".zig") for p in file_paths)

    def summarize_file(self, file, objective):
        raise NotImplementedError
