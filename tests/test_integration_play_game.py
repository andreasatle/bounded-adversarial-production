from baps.adapters.project_adapter import VerificationResult
from baps.game.engine import play_game
from baps.game.roles import PriorExportFeedback
from baps.models.models import FakeModelClient, ToolCall
from baps.northstar.northstar_projection import ProjectionType, StateView
from baps.state.state import GameSpec
import baps.state.state as state_module
def test_play_game_uses_adapter_provided_state_view_prompt_and_parser() -> None:
    from baps.models.models import ToolDefinition

    class _PlayAdapter:
        project_type = "document"
        supported_delta_type = "DeltaDocumentState"

        def __init__(self) -> None:
            self.calls: list[str] = []

        def create_initial_state(self, _config):
            raise NotImplementedError

        def build_state_view(self, _state, _game_spec, summarization_context=None):
            self.calls.append("build_state_view")
            return StateView(
                id="state-view:test",
                projection_type=ProjectionType.NORTH_STAR,
                content="{}",
                input_fingerprint="x",
                metadata={},
            )

        def render_blue_prompt(
            self, _state_view, _game_spec, _attempt_number, _previous_feedback
        ):
            self.calls.append("render_blue_prompt")
            return "blue-prompt"

        def build_blue_output_format(self):
            return None

        def build_blue_tools(self):
            self.calls.append("build_blue_tools")
            return [ToolDefinition(name="append_section", description="Append", parameters={})]

        def tool_call_to_delta(self, _tool_call):
            self.calls.append("tool_call_to_delta")
            return state_module.DeltaDocumentState(
                artifact_id="main-document",
                operation="append_section",
                payload=state_module.AppendSectionDelta(
                    section=state_module.Section(title="Intro", body="Body")
                ),
            )

    adapter = _PlayAdapter()
    spec = GameSpec(
        objective="Add section",
        target_artifact_id="main-document",
        allowed_delta_type="DeltaDocumentState",
        success_condition="section exists",
    )
    state = state_module.State(
        northstar=state_module.NorthStar(artifacts=()),
        artifacts=(state_module.DocumentArtifact(id="main-document", sections=()),),
    )
    delta = play_game(
        state,
        spec,
        adapter=adapter,
        model_client=FakeModelClient(
            tool_responses=[ToolCall(name="append_section", arguments={"artifact_id": "main-document", "title": "Intro", "body": "Body"})]
        ),
        red_model_client=FakeModelClient(['{"disposition":"accept","rationale":"ok"}']),
        referee_model_client=FakeModelClient(['{"disposition":"accept","rationale":"ok"}']),
    )
    assert isinstance(delta, state_module.DeltaDocumentState)
    assert adapter.calls == ["build_state_view", "render_blue_prompt", "build_blue_tools", "tool_call_to_delta"]


def test_play_game_pre_seeds_verification_result_as_previous_feedback(monkeypatch) -> None:

    captured_feedback: list[object] = []

    class _CapturingAdapter:
        project_type = "coding"
        supported_delta_type = "DeltaCodingState"

        def build_state_view(self, state, game_spec, summarization_context=None):
            from baps.northstar.northstar_projection import ProjectionType, StateView
            return StateView(
                id="sv", projection_type=ProjectionType.NORTH_STAR,
                content="view", input_fingerprint="fp", metadata={}
            )

        def render_blue_prompt(self, state_view, game_spec, attempt_number, previous_feedback):
            captured_feedback.append(previous_feedback)
            return "blue prompt"

        def build_blue_output_format(self):
            return None

        def build_blue_tools(self):
            return []

        def parse_blue_delta(self, text):
            raise ValueError("no delta — max_attempts=1 so this exhausts attempts")

        def render_red_prompt_supplement(self, *a, **kw):
            return ""

        def render_referee_prompt_supplement(self, *a, **kw):
            return ""

    vr = VerificationResult(
        command="uv run pytest", cwd="/tmp", exit_code=1,
        stdout="FAILED tests/test_foo.py::test_x - AssertionError\n",
        stderr="", passed=False,
    )
    state = state_module.State(
        northstar=state_module.NorthStar(artifacts=()),
        artifacts=(state_module.CodingArtifact(id="main-codebase", files=()),),
    )
    game_spec = GameSpec(
        objective="Fix tests",
        target_artifact_id="main-codebase",
        allowed_delta_type="DeltaCodingState",
        success_condition="tests pass",
    )

    # tool_responses=[None] makes generate_with_tools return None → falls through to generate().
    # parse_blue_delta raises ValueError → attempt exhausted → returns None.
    result = play_game(
        state, game_spec,
        adapter=_CapturingAdapter(),
        model_client=FakeModelClient(tool_responses=[None], responses=["not valid json"]),
        red_model_client=FakeModelClient(responses=[]),
        referee_model_client=FakeModelClient(responses=[]),
        verification_result=vr,
        max_attempts=1,
    )

    assert result is None
    assert len(captured_feedback) >= 1
    fb = captured_feedback[0]
    assert fb is not None
    assert isinstance(fb, PriorExportFeedback)
    assert fb.prior_export_verification["exit_code"] == 1
    assert fb.prior_export_verification["passed"] is False
