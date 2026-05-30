"""Renders Blue, Red, and Referee prompts for coding-type projects."""

from __future__ import annotations

from baps.adapters.project_adapter import VerificationResult, render_blue_prompt_core
from baps.northstar.northstar_projection import StateView
from baps.plugins.language_plugin import LanguagePlugin
from baps.state.state import GameSpec
from baps.game.roles import AttemptRejectionFeedback, PlayGameFeedback, PriorExportFeedback

from .common import _BLUE_CONTENT_FORBIDDEN_MARKERS


def _render_verification_feedback_section(
    previous_feedback: PlayGameFeedback | None,
    plugin: LanguagePlugin,
) -> str:
    """Render a verification failure summary block for Blue from prior export or candidate feedback."""
    if previous_feedback is None:
        return ""
    section = ""
    if isinstance(previous_feedback, PriorExportFeedback):
        pv = previous_feedback.prior_export_verification
        exit_code = pv.get("exit_code", "?")
        stdout = str(pv.get("stdout", ""))
        failures = plugin.parse_test_failures(stdout)
        if failures:
            lines = "\n".join(f"  - {f['test_id']}: {f['reason']}" for f in failures)
            section += (
                f"\nPrevious export verification failed (exit_code={exit_code}):\n"
                f"{lines}\n"
                "- Fix these specific test failures in your delta.\n"
            )
        elif exit_code not in (0, "0"):
            section += (
                f"\nPrevious export verification failed (exit_code={exit_code}).\n"
                "- Inspect prior_export_verification in previous_feedback_json and repair the cause.\n"
            )
    elif isinstance(previous_feedback, AttemptRejectionFeedback) and previous_feedback.candidate_verification is not None:
        cv = previous_feedback.candidate_verification
        exit_code = cv.get("exit_code", "?")
        stdout = str(cv.get("stdout", ""))
        failures = plugin.parse_test_failures(stdout)
        if failures:
            lines = "\n".join(f"  - {f['test_id']}: {f['reason']}" for f in failures)
            section += (
                f"\nCandidate verification failed (exit_code={exit_code}) — your last delta did not pass tests:\n"
                f"{lines}\n"
                "- Repair these test failures in this attempt.\n"
            )
        elif exit_code not in (0, "0"):
            section += (
                f"\nCandidate verification failed (exit_code={exit_code}).\n"
                "- Inspect candidate_verification in previous_feedback_json and repair the cause.\n"
            )
    return section


def render_coding_blue_prompt(
    state_view: StateView,
    game_spec: GameSpec,
    attempt_number: int,
    previous_feedback: PlayGameFeedback | None,
    plugin: LanguagePlugin,
) -> str:
    """Render the full Blue prompt for a coding project, including delta shape rules and verification context."""
    verification_section = _render_verification_feedback_section(previous_feedback, plugin)
    coding_delta_instructions = (
        "Coding delta rules:\n"
        "- Use write_files (plural) to write one or more files in a single delta — preferred.\n"
        "- Use write_file (singular) only when writing exactly one file.\n"
        "- Use delete_file to remove a file that is no longer needed.\n"
        "- file paths and content must be non-empty strings.\n"
        "- Prefer production code under src/.\n"
        "- Prefer tests under tests/.\n"
        "- Prefer pytest-discoverable tests at tests/test_*.py.\n"
        "- Test files must import from their corresponding production module using standard Python imports (e.g. from src.mymodule import myfunction).\n"
        "- Test files must NOT redefine or duplicate production functions.\n"
        "- Keep code and tests as separate files (do not embed unittest in production file).\n"
        "- content must be a valid JSON string: escape internal double quotes as \\\" and newlines as \\n.\n"
        "- File content MUST contain final artifact content only — no reasoning, planning notes, self-corrections, or alternative explanations.\n"
        f"- Forbidden markers in content include: {', '.join(repr(m) for m in _BLUE_CONTENT_FORBIDDEN_MARKERS)}.\n"
        "- Return one complete JSON object with balanced braces.\n"
        "Preferred JSON shape (write_files — one or more files):\n"
        "{\n"
        '  "artifact_id": "<game_spec.target_artifact_id>",\n'
        '  "operation": "write_files",\n'
        '  "payload": {\n'
        '    "files": [\n'
        '      {"path": "<relative path>", "content": "<full file content>"},\n'
        '      {"path": "<another path>", "content": "<full file content>"}\n'
        "    ]\n"
        "  }\n"
        "}\n"
        "Alternative shape (write_file — single file only):\n"
        "{\n"
        '  "artifact_id": "<game_spec.target_artifact_id>",\n'
        '  "operation": "write_file",\n'
        '  "payload": {\n'
        '    "file": {\n'
        '      "path": "<relative path>",\n'
        '      "content": "<full file content>"\n'
        "    }\n"
        "  }\n"
        "}\n"
        "Alternative shape (delete_file — remove a file):\n"
        "{\n"
        '  "artifact_id": "<game_spec.target_artifact_id>",\n'
        '  "operation": "delete_file",\n'
        '  "payload": {\n'
        '    "path": "<relative path to delete>"\n'
        "  }\n"
        "}"
        f"{verification_section}"
    )
    return render_blue_prompt_core(
        state_view=state_view,
        game_spec=game_spec,
        attempt_number=attempt_number,
        previous_feedback=previous_feedback,
        project_delta_instructions=coding_delta_instructions,
    )


def _truncate_lines(text: str, max_lines: int) -> str:
    """Return text truncated to max_lines, appending a count of omitted lines if truncated."""
    lines = text.splitlines()
    if len(lines) <= max_lines:
        return text
    return "\n".join(lines[:max_lines]) + f"\n... ({len(lines) - max_lines} more lines)"


def _render_coding_evaluation_supplement(verification_result: VerificationResult | None) -> str:
    """Render coding-specific Red/Referee evaluation guidance, including verification evidence hints."""
    base = (
        "Coding evaluation guidance:\n"
        "- target_artifact_id is the artifact id, not a file path.\n"
        "- For write_file: file path belongs in payload.file.path.\n"
        "- For write_files: file paths belong in payload.files[].path.\n"
        "- Pytest tests containing assert statements are not empty.\n"
        "- Do not reject tests as empty if assertions are present.\n"
        "- If success_condition only requires non-empty tests, basic asserted tests satisfy that condition.\n"
        "- If verification evidence exists, reason from exit_code/stdout/stderr.\n"
    )
    if verification_result is not None:
        return base + "- If pytest discovered tests, do not claim test files are empty.\n"
    return base
