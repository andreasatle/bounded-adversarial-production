import pytest
from pydantic import ValidationError

from baps.state import NorthStar, State, StateArtifact
from baps.northstar_projection import (
    NorthStarView,
    NorthStarProjectionRenderer,
    NorthStarProjectionInput,
    NorthStarProjectionItem,
    ProjectionPolicy,
    ProjectionType,
    StateView,
    fingerprint_northstar_projection_input,
    render_northstar_view,
    render_northstar_projection,
)


def _item(
    content: str,
    source: str,
    authority: str,
    status: str,
    item_id: str = "item",
) -> NorthStarProjectionItem:
    return NorthStarProjectionItem(
        id=item_id,
        content=content,
        source=source,
        authority=authority,
        status=status,
    )


def test_render_includes_all_sections_in_required_order() -> None:
    data = NorthStarProjectionInput(
        framework_policy=(_item("Framework rule", "framework-doc", "framework", "active"),),
        project_state=(_item("Accepted project fact", "state-file", "project", "accepted"),),
        blackboard_history=(_item("Historical rationale", "blackboard-log", "historical", "recorded"),),
        runtime_context=(_item("Current run context", "runtime", "temporary", "active"),),
    )

    rendered = render_northstar_projection(data)

    framework_idx = rendered.index("## Framework Policy")
    project_idx = rendered.index("## Project State")
    history_idx = rendered.index("## Blackboard History")
    runtime_idx = rendered.index("## Runtime Context")

    assert framework_idx < project_idx < history_idx < runtime_idx


def test_verbatim_content_is_preserved_exactly() -> None:
    verbatim = "Exact  content\\nwith   spacing\\nand\\ttabs"
    data = NorthStarProjectionInput(
        project_state=(
            NorthStarProjectionItem(
                id="state-item-1",
                content=verbatim,
                source="state-src",
                authority="project",
                status="accepted",
                projection_policy=ProjectionPolicy.VERBATIM,
            ),
        ),
    )
    rendered = render_northstar_projection(data)
    assert f"1. {verbatim}" in rendered


def test_rendered_items_include_provenance_fields() -> None:
    data = NorthStarProjectionInput(
        framework_policy=(_item("Policy", "policy-src", "framework", "active"),),
        project_state=(_item("Project", "project-src", "project", "accepted"),),
        blackboard_history=(_item("History", "history-src", "historical", "recorded"),),
        runtime_context=(_item("Runtime", "runtime-src", "temporary", "active"),),
    )

    rendered = render_northstar_projection(data)

    assert "id: item" in rendered
    assert "source: policy-src" in rendered
    assert "authority: framework" in rendered
    assert "status: active" in rendered

    assert "source: project-src" in rendered
    assert "authority: project" in rendered
    assert "status: accepted" in rendered

    assert "source: history-src" in rendered
    assert "authority: historical" in rendered
    assert "status: recorded" in rendered

    assert "source: runtime-src" in rendered
    assert "authority: temporary" in rendered


def test_framework_policy_and_project_state_remain_distinct_categories() -> None:
    data = NorthStarProjectionInput(
        framework_policy=(
            _item(
                "FRAMEWORK_ONLY_MARKER",
                "framework-source",
                "framework",
                "active",
            ),
        ),
        project_state=(
            _item(
                "PROJECT_ONLY_MARKER",
                "project-source",
                "project",
                "accepted",
            ),
        ),
    )

    rendered = render_northstar_projection(data)

    framework_section_start = rendered.index("## Framework Policy")
    project_section_start = rendered.index("## Project State")
    history_section_start = rendered.index("## Blackboard History")

    framework_section = rendered[framework_section_start:project_section_start]
    project_section = rendered[project_section_start:history_section_start]

    assert "FRAMEWORK_ONLY_MARKER" in framework_section
    assert "PROJECT_ONLY_MARKER" not in framework_section
    assert "PROJECT_ONLY_MARKER" in project_section
    assert "FRAMEWORK_ONLY_MARKER" not in project_section


def test_repeated_rendering_of_same_input_is_identical() -> None:
    data = NorthStarProjectionInput(
        framework_policy=(_item("Rule A", "policy", "framework", "active"),),
        project_state=(_item("Fact A", "state", "project", "accepted"),),
        blackboard_history=(_item("History A", "bb", "historical", "recorded"),),
        runtime_context=(_item("Runtime A", "ctx", "temporary", "active"),),
    )

    first = render_northstar_projection(data)
    second = render_northstar_projection(data)

    assert first == second


@pytest.mark.parametrize(
    "field_name, value",
    [
        ("id", " "),
        ("content", " "),
        ("input_fingerprint", " "),
    ],
)
def test_projection_artifact_rejects_empty_required_strings(field_name: str, value: str) -> None:
    payload = {
        "id": "projection-1",
        "projection_type": ProjectionType.NORTH_STAR,
        "content": "content",
        "input_fingerprint": "fingerprint",
    }
    payload[field_name] = value
    with pytest.raises(ValidationError):
        StateView.model_validate(payload)


def test_projection_artifact_metadata_defaults_are_isolated_per_instance() -> None:
    first = StateView(
        id="projection-1",
        projection_type=ProjectionType.NORTH_STAR,
        content="content-1",
        input_fingerprint="fp-1",
    )
    second = StateView(
        id="projection-2",
        projection_type=ProjectionType.NORTH_STAR,
        content="content-2",
        input_fingerprint="fp-2",
    )

    first.metadata["mutated"] = "yes"
    assert first.metadata == {"mutated": "yes"}
    assert second.metadata == {}


def test_projection_artifact_rejects_invalid_projection_type() -> None:
    with pytest.raises(ValidationError):
        StateView(
            id="projection-1",
            projection_type="invalid_type",
            content="content",
            input_fingerprint="fingerprint",
        )


def test_projection_artifact_accepts_north_star_projection_type() -> None:
    artifact = StateView(
        id="projection-1",
        projection_type=ProjectionType.NORTH_STAR,
        content="content",
        input_fingerprint="fingerprint",
    )
    assert artifact.projection_type is ProjectionType.NORTH_STAR


def test_render_northstar_view_preserves_markdown_content() -> None:
    data = NorthStarProjectionInput(
        framework_policy=(_item("Policy A", "policy", "framework", "active"),),
        project_state=(_item("State A", "state", "project", "accepted"),),
        blackboard_history=(_item("History A", "history", "historical", "recorded"),),
        runtime_context=(_item("Runtime A", "runtime", "temporary", "active"),),
    )
    expected_markdown = render_northstar_projection(data)

    artifact = render_northstar_view(data)

    assert artifact.content == expected_markdown
    assert artifact.projection_type is ProjectionType.NORTH_STAR


def test_identical_northstar_inputs_produce_identical_fingerprints() -> None:
    first = NorthStarProjectionInput(
        framework_policy=(_item("Policy A", "policy", "framework", "active"),),
        project_state=(_item("State A", "state", "project", "accepted"),),
        blackboard_history=(_item("History A", "history", "historical", "recorded"),),
        runtime_context=(_item("Runtime A", "runtime", "temporary", "active"),),
    )
    second = NorthStarProjectionInput(
        framework_policy=(_item("Policy A", "policy", "framework", "active"),),
        project_state=(_item("State A", "state", "project", "accepted"),),
        blackboard_history=(_item("History A", "history", "historical", "recorded"),),
        runtime_context=(_item("Runtime A", "runtime", "temporary", "active"),),
    )

    assert fingerprint_northstar_projection_input(first) == fingerprint_northstar_projection_input(
        second
    )


def test_changed_northstar_inputs_produce_different_fingerprints() -> None:
    first = NorthStarProjectionInput(
        project_state=(_item("State A", "state", "project", "accepted"),),
    )
    second = NorthStarProjectionInput(
        project_state=(_item("State B", "state", "project", "accepted"),),
    )

    assert fingerprint_northstar_projection_input(first) != fingerprint_northstar_projection_input(
        second
    )


def test_projection_artifact_is_distinct_from_state_and_does_not_mutate_state() -> None:
    state = State(
        northstar=NorthStar(artifacts=(StateArtifact(id="n1", kind="document"),)),
        artifacts=(StateArtifact(id="a1", kind="git_repository"),),
    )
    before = state.model_dump(mode="json")
    projection_input = NorthStarProjectionInput(
        project_state=(_item("State A", "state", "project", "accepted"),),
    )

    artifact = render_northstar_view(projection_input)

    assert not isinstance(artifact, State)
    assert state.model_dump(mode="json") == before


def test_repeated_artifact_generation_with_identical_input_is_byte_identical() -> None:
    projection_input = NorthStarProjectionInput(
        framework_policy=(_item("Policy A", "policy", "framework", "active"),),
        project_state=(_item("State A", "state", "project", "accepted"),),
    )

    first = render_northstar_view(projection_input)
    second = render_northstar_view(projection_input)

    assert first.model_dump_json() == second.model_dump_json()


def test_modifying_input_after_render_does_not_mutate_projection_artifact() -> None:
    item = NorthStarProjectionItem(
        id="state-item-1",
        content="State A",
        source="state",
        authority="project",
        status="accepted",
    )
    projection_input = NorthStarProjectionInput(project_state=(item,))
    artifact = render_northstar_view(projection_input)
    before_content = artifact.content
    before_fingerprint = artifact.input_fingerprint

    item.content = "State B"
    item.status = "rejected"

    assert artifact.content == before_content
    assert artifact.input_fingerprint == before_fingerprint


@pytest.mark.parametrize(
    "policy",
    [
        ProjectionPolicy.SUMMARIZED,
        ProjectionPolicy.FILTERED,
        ProjectionPolicy.DIRECT,
    ],
)
def test_renderer_rejects_unsupported_projection_policies(policy: ProjectionPolicy) -> None:
    data = NorthStarProjectionInput(
        project_state=(
            NorthStarProjectionItem(
                id="state-item-1",
                content="State A",
                source="state",
                authority="project",
                status="accepted",
                projection_policy=policy,
            ),
        ),
    )

    with pytest.raises(ValueError, match="unsupported projection policy"):
        render_northstar_projection(data)


def test_northstar_projection_renderer_returns_projection_artifact() -> None:
    renderer = NorthStarProjectionRenderer()
    data = NorthStarProjectionInput(
        project_state=(_item("State A", "state", "project", "accepted"),),
    )

    artifact = renderer.render(data)

    assert isinstance(artifact, StateView)
    assert isinstance(artifact, NorthStarView)


def test_northstar_projection_renderer_repeated_renders_are_byte_identical() -> None:
    renderer = NorthStarProjectionRenderer()
    data = NorthStarProjectionInput(
        framework_policy=(_item("Policy A", "policy", "framework", "active"),),
        project_state=(_item("State A", "state", "project", "accepted"),),
        blackboard_history=(_item("History A", "history", "historical", "recorded"),),
        runtime_context=(_item("Runtime A", "runtime", "temporary", "active"),),
    )

    first = renderer.render(data)
    second = renderer.render(data)

    assert first.model_dump_json() == second.model_dump_json()


def test_northstar_projection_renderer_does_not_mutate_inputs() -> None:
    renderer = NorthStarProjectionRenderer()
    item = NorthStarProjectionItem(
        id="state-item-1",
        content="State A",
        source="state",
        authority="project",
        status="accepted",
    )
    data = NorthStarProjectionInput(project_state=(item,))
    before = data.model_dump(mode="json")

    _ = renderer.render(data)

    after = data.model_dump(mode="json")
    assert after == before


@pytest.mark.parametrize("bad_id", ["", "   ", "\n\t"])
def test_northstar_projection_item_rejects_empty_id(bad_id: str) -> None:
    with pytest.raises(ValidationError):
        NorthStarProjectionItem(
            id=bad_id,
            content="State A",
            source="state",
            authority="project",
            status="accepted",
        )


def test_item_id_appears_in_rendered_provenance() -> None:
    data = NorthStarProjectionInput(
        project_state=(
            NorthStarProjectionItem(
                id="state-item-123",
                content="State A",
                source="state",
                authority="project",
                status="accepted",
            ),
        ),
    )
    rendered = render_northstar_projection(data)
    assert "id: state-item-123" in rendered


def test_changing_item_id_changes_fingerprint() -> None:
    first = NorthStarProjectionInput(
        project_state=(
            NorthStarProjectionItem(
                id="state-item-1",
                content="State A",
                source="state",
                authority="project",
                status="accepted",
            ),
        ),
    )
    second = NorthStarProjectionInput(
        project_state=(
            NorthStarProjectionItem(
                id="state-item-2",
                content="State A",
                source="state",
                authority="project",
                status="accepted",
            ),
        ),
    )
    assert fingerprint_northstar_projection_input(first) != fingerprint_northstar_projection_input(
        second
    )


def test_item_id_does_not_affect_item_ordering() -> None:
    data = NorthStarProjectionInput(
        project_state=(
            NorthStarProjectionItem(
                id="z-item",
                content="First content",
                source="state",
                authority="project",
                status="accepted",
            ),
            NorthStarProjectionItem(
                id="a-item",
                content="Second content",
                source="state",
                authority="project",
                status="accepted",
            ),
        ),
    )
    rendered = render_northstar_projection(data)
    assert rendered.index("1. First content") < rendered.index("2. Second content")
