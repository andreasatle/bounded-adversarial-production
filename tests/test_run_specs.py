from pathlib import Path

import pytest

from baps.run_specs import RunSpec, load_run_spec


def test_load_run_spec_valid_yaml(tmp_path: Path) -> None:
    path = tmp_path / "run.yaml"
    path.write_text(
        "\n".join(
            [
                "model:",
                "  provider: ollama",
                "  name: gemma3",
                "game:",
                "  type: documentation-refinement",
                "  subject: Subj",
                "  goal: Goal",
                "  target_kind: documentation",
                "  target_ref: README.md",
                "  max_rounds: 2",
                "context_files:",
                "  - docs/README.md",
                "context:",
                "  - id: goals_doc",
                "    role: goals",
                "    ref: docs/GOALS.md",
                "    authority: context",
                "state:",
                "  manifest: examples/state_manifests/baps_project_state.json",
                "  sources:",
                "    - architecture",
            ]
        ),
        encoding="utf-8",
    )

    spec = load_run_spec(path)
    assert isinstance(spec, RunSpec)
    assert spec.model.name == "gemma3"
    assert spec.game.subject == "Subj"
    assert spec.state is not None
    assert spec.state.sources == ["architecture"]
    assert len(spec.context) == 1
    assert spec.context[0].id == "goals_doc"


def test_load_run_spec_missing_file_fails(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_run_spec(tmp_path / "missing.yaml")


def test_load_run_spec_invalid_yaml_fails(tmp_path: Path) -> None:
    path = tmp_path / "bad.yaml"
    path.write_text("game:\n  subject: [oops", encoding="utf-8")
    with pytest.raises(ValueError, match="invalid YAML"):
        load_run_spec(path)


def test_load_run_spec_invalid_schema_fails(tmp_path: Path) -> None:
    path = tmp_path / "bad-schema.yaml"
    path.write_text("game:\n  subject: x\n", encoding="utf-8")
    with pytest.raises(ValueError, match="invalid RunSpec schema"):
        load_run_spec(path)


def test_example_run_spec_parses() -> None:
    spec = load_run_spec(Path("examples/runs/fake_goal_audit.yaml"))
    assert spec.game.subject
    assert spec.game.goal
    assert spec.game.target_kind


def test_run_spec_context_entry_rejects_blank_fields(tmp_path: Path) -> None:
    path = tmp_path / "bad-context.yaml"
    path.write_text(
        "\n".join(
            [
                "game:",
                "  type: documentation-refinement",
                "  subject: Subj",
                "  goal: Goal",
                "  target_kind: documentation",
                "context:",
                "  - id: good",
                "    role: ' '",
                "    ref: docs/GOALS.md",
            ]
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="invalid RunSpec schema"):
        load_run_spec(path)
