from pathlib import Path

import pytest
from pydantic import ValidationError

from baps.state import DocumentArtifact, State, StateArtifact
from baps.state_store import JsonStateStore


def _sample_state() -> State:
    return State(
        artifacts=(
            DocumentArtifact(id="artifact-1"),
            StateArtifact(id="artifact-2", kind="git_repository"),
        ),
    )


def test_json_state_store_save_then_load_round_trips_state(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    store = JsonStateStore(path)
    state = _sample_state()

    store.save(state)
    loaded = store.load()

    assert loaded == state


def test_json_state_store_load_validates_state_and_raises_on_malformed_state(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    path.write_text('{"artifacts": [{"kind": "document"}]}', encoding="utf-8")
    store = JsonStateStore(path)

    with pytest.raises(ValidationError):
        store.load()


def test_json_state_store_save_creates_parent_directory(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "state" / "state.json"
    store = JsonStateStore(path)

    store.save(_sample_state())

    assert path.exists()


def test_json_state_store_save_does_not_mutate_input_state(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    store = JsonStateStore(path)
    state = _sample_state()
    before = state.model_dump(mode="json")

    store.save(state)

    after = state.model_dump(mode="json")
    assert after == before


def test_json_state_store_instances_do_not_share_state(tmp_path: Path) -> None:
    path_one = tmp_path / "one.json"
    path_two = tmp_path / "two.json"
    store_one = JsonStateStore(path_one)
    store_two = JsonStateStore(path_two)

    state_one = State(
        artifacts=(StateArtifact(id="a1", kind="git_repository"),),
    )
    state_two = State(
        artifacts=(DocumentArtifact(id="a2"),),
    )

    store_one.save(state_one)
    store_two.save(state_two)

    assert store_one.load() == state_one
    assert store_two.load() == state_two


def test_json_state_store_load_missing_file_raises_clear_file_not_found(tmp_path: Path) -> None:
    path = tmp_path / "missing-state.json"
    store = JsonStateStore(path)

    with pytest.raises(FileNotFoundError, match="state file not found"):
        store.load()
