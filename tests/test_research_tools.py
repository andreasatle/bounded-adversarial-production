"""Tests for the generic module/entity research tool system."""

from __future__ import annotations

from baps.state.state import (
    CodeFile,
    CodingArtifact,
    DocumentArtifact,
    NorthStar,
    Section,
    State,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _coding_state(files: list[tuple[str, str]], language: str = "python") -> State:
    return State(
        northstar=NorthStar(artifacts=()),
        artifacts=(
            CodingArtifact(
                id="art",
                language=language,
                files=tuple(CodeFile(path=p, content=c) for p, c in files),
            ),
        ),
    )


def _document_state(sections: list[tuple[str, str]]) -> State:
    return State(
        northstar=NorthStar(artifacts=()),
        artifacts=(
            DocumentArtifact(
                id="doc",
                sections=tuple(Section(title=t, body=b) for t, b in sections),
            ),
        ),
    )


# ---------------------------------------------------------------------------
# supported_filters — language plugins
# ---------------------------------------------------------------------------


def test_python_plugin_supported_filters_returns_api_tests_full() -> None:
    from baps.plugins.language_python import PythonLanguagePlugin

    assert PythonLanguagePlugin().supported_filters() == ["api", "tests", "full"]


def test_rust_plugin_supported_filters_returns_api_tests_full() -> None:
    from baps.plugins.language_rust import RustLanguagePlugin

    assert RustLanguagePlugin().supported_filters() == ["api", "tests", "full"]


def test_zig_plugin_supported_filters_returns_api_tests_full() -> None:
    from baps.plugins.language_zig import ZigLanguagePlugin

    assert ZigLanguagePlugin().supported_filters() == ["api", "tests", "full"]


def test_zig_plugin_supported_filters_includes_tests() -> None:
    from baps.plugins.language_zig import ZigLanguagePlugin

    assert "tests" in ZigLanguagePlugin().supported_filters()


def test_language_plugin_has_no_summarize_file_method() -> None:
    from baps.plugins.language_plugin import LanguagePlugin

    assert not hasattr(LanguagePlugin, "summarize_file")


# ---------------------------------------------------------------------------
# supported_filters — adapters
# ---------------------------------------------------------------------------


def test_document_adapter_supported_filters() -> None:
    from baps.adapters.document_adapter import DocumentProjectAdapter

    assert DocumentProjectAdapter().supported_filters() == ["summary", "full"]


def test_coding_adapter_supported_filters_includes_api() -> None:
    from baps.adapters.coding_adapter import CodingProjectAdapter

    assert "api" in CodingProjectAdapter().supported_filters()


def test_coding_adapter_supported_filters_includes_tests() -> None:
    from baps.adapters.coding_adapter import CodingProjectAdapter

    assert "tests" in CodingProjectAdapter().supported_filters()


def test_coding_adapter_supported_filters_includes_full() -> None:
    from baps.adapters.coding_adapter import CodingProjectAdapter

    assert "full" in CodingProjectAdapter().supported_filters()


def test_audit_adapter_supported_filters() -> None:
    from baps.adapters.audit_adapter import AuditProjectAdapter

    assert AuditProjectAdapter().supported_filters() == ["summary", "full"]


# ---------------------------------------------------------------------------
# PythonLanguagePlugin.extract_api
# ---------------------------------------------------------------------------

_SIMPLE_PY = """\
\"\"\"Module docstring.

More details.
\"\"\"
import os
import sys


def add(x: int, y: int) -> int:
    \"\"\"Add two numbers.\"\"\"
    return x + y


def no_doc(z: float) -> None:
    pass


class MyClass(Base):
    \"\"\"A class.\"\"\"

    def method(self, val: str) -> bool:
        \"\"\"Check val.\"\"\"
        return bool(val)

    def undoc(self) -> None:
        pass
"""


def test_extract_api_includes_module_docstring_first_line() -> None:
    from baps.plugins.language_python import PythonLanguagePlugin

    file = CodeFile(path="m.py", content=_SIMPLE_PY)
    result = PythonLanguagePlugin().extract_api(file)
    assert '"""Module docstring."""' in result


def test_extract_api_excludes_module_docstring_second_line() -> None:
    from baps.plugins.language_python import PythonLanguagePlugin

    file = CodeFile(path="m.py", content=_SIMPLE_PY)
    result = PythonLanguagePlugin().extract_api(file)
    assert "More details" not in result


def test_extract_api_includes_imports() -> None:
    from baps.plugins.language_python import PythonLanguagePlugin

    file = CodeFile(path="m.py", content=_SIMPLE_PY)
    result = PythonLanguagePlugin().extract_api(file)
    assert "import os" in result
    assert "import sys" in result


def test_extract_api_includes_function_signature() -> None:
    from baps.plugins.language_python import PythonLanguagePlugin

    file = CodeFile(path="m.py", content=_SIMPLE_PY)
    result = PythonLanguagePlugin().extract_api(file)
    assert "def add(x: int, y: int) -> int:" in result


def test_extract_api_includes_function_docstring_first_line() -> None:
    from baps.plugins.language_python import PythonLanguagePlugin

    file = CodeFile(path="m.py", content=_SIMPLE_PY)
    result = PythonLanguagePlugin().extract_api(file)
    assert '"""Add two numbers."""' in result


def test_extract_api_omits_none_docstrings() -> None:
    from baps.plugins.language_python import PythonLanguagePlugin

    file = CodeFile(path="m.py", content=_SIMPLE_PY)
    result = PythonLanguagePlugin().extract_api(file)
    lines = result.splitlines()
    no_doc_idx = next(i for i, l in enumerate(lines) if "def no_doc" in l)
    # Next non-empty line should not be a docstring
    following = [l for l in lines[no_doc_idx + 1 :] if l.strip()]
    assert not (following and following[0].strip().startswith('"""'))


def test_extract_api_includes_class_with_bases() -> None:
    from baps.plugins.language_python import PythonLanguagePlugin

    file = CodeFile(path="m.py", content=_SIMPLE_PY)
    result = PythonLanguagePlugin().extract_api(file)
    assert "class MyClass(Base):" in result


def test_extract_api_includes_class_docstring_first_line() -> None:
    from baps.plugins.language_python import PythonLanguagePlugin

    file = CodeFile(path="m.py", content=_SIMPLE_PY)
    result = PythonLanguagePlugin().extract_api(file)
    assert '"""A class."""' in result


def test_extract_api_includes_method_signatures() -> None:
    from baps.plugins.language_python import PythonLanguagePlugin

    file = CodeFile(path="m.py", content=_SIMPLE_PY)
    result = PythonLanguagePlugin().extract_api(file)
    assert "def method(self, val: str) -> bool:" in result


def test_extract_api_includes_method_docstring_first_line() -> None:
    from baps.plugins.language_python import PythonLanguagePlugin

    file = CodeFile(path="m.py", content=_SIMPLE_PY)
    result = PythonLanguagePlugin().extract_api(file)
    assert '"""Check val."""' in result


def test_extract_api_omits_function_body() -> None:
    from baps.plugins.language_python import PythonLanguagePlugin

    file = CodeFile(path="m.py", content=_SIMPLE_PY)
    result = PythonLanguagePlugin().extract_api(file)
    assert "return x + y" not in result


def test_extract_api_omits_method_body() -> None:
    from baps.plugins.language_python import PythonLanguagePlugin

    file = CodeFile(path="m.py", content=_SIMPLE_PY)
    result = PythonLanguagePlugin().extract_api(file)
    assert "return bool(val)" not in result


def test_extract_api_class_without_base() -> None:
    from baps.plugins.language_python import PythonLanguagePlugin

    src = "class Plain:\n    pass\n"
    file = CodeFile(path="x.py", content=src)
    result = PythonLanguagePlugin().extract_api(file)
    assert "class Plain:" in result
    assert "Plain()" not in result


def test_extract_api_async_function() -> None:
    from baps.plugins.language_python import PythonLanguagePlugin

    src = 'async def fetch() -> str:\n    """Fetch data."""\n    return \'\'\n'
    file = CodeFile(path="x.py", content=src)
    result = PythonLanguagePlugin().extract_api(file)
    assert "async def fetch() -> str:" in result


def test_extract_api_decorator_preserved() -> None:
    from baps.plugins.language_python import PythonLanguagePlugin

    src = "@staticmethod\ndef helper() -> None:\n    pass\n"
    file = CodeFile(path="x.py", content=src)
    result = PythonLanguagePlugin().extract_api(file)
    assert "@staticmethod" in result


def test_extract_api_syntax_error_returns_raw_content() -> None:
    from baps.plugins.language_python import PythonLanguagePlugin

    src = "def broken(:\n    pass\n"
    file = CodeFile(path="x.py", content=src)
    result = PythonLanguagePlugin().extract_api(file)
    assert "broken" in result


# ---------------------------------------------------------------------------
# PythonLanguagePlugin.extract_tests
# ---------------------------------------------------------------------------

_TEST_PY = """\
def test_addition() -> None:
    \"\"\"Test that addition works.\"\"\"
    assert 1 + 1 == 2


def test_subtraction() -> None:
    assert 2 - 1 == 1


def helper() -> None:
    pass


class TestSuite:
    def test_method(self) -> None:
        \"\"\"Test method inside class.\"\"\"
        pass
"""


def test_extract_tests_starts_with_tests_header() -> None:
    from baps.plugins.language_python import PythonLanguagePlugin

    file = CodeFile(path="test_x.py", content=_TEST_PY)
    result = PythonLanguagePlugin().extract_tests(file)
    assert result.startswith("Tests:")


def test_extract_tests_lists_test_functions() -> None:
    from baps.plugins.language_python import PythonLanguagePlugin

    file = CodeFile(path="test_x.py", content=_TEST_PY)
    result = PythonLanguagePlugin().extract_tests(file)
    assert "test_addition" in result
    assert "test_subtraction" in result


def test_extract_tests_excludes_non_test_functions() -> None:
    from baps.plugins.language_python import PythonLanguagePlugin

    file = CodeFile(path="test_x.py", content=_TEST_PY)
    result = PythonLanguagePlugin().extract_tests(file)
    assert "helper" not in result


def test_extract_tests_includes_docstring_first_line() -> None:
    from baps.plugins.language_python import PythonLanguagePlugin

    file = CodeFile(path="test_x.py", content=_TEST_PY)
    result = PythonLanguagePlugin().extract_tests(file)
    assert "Test that addition works" in result


def test_extract_tests_omits_docstring_for_undocumented_test() -> None:
    from baps.plugins.language_python import PythonLanguagePlugin

    file = CodeFile(path="test_x.py", content=_TEST_PY)
    result = PythonLanguagePlugin().extract_tests(file)
    # test_subtraction has no docstring — just its name
    lines = result.splitlines()
    sub_line = next((l for l in lines if "test_subtraction" in l), None)
    assert sub_line is not None
    assert ":" not in sub_line.split("test_subtraction")[1]


def test_extract_tests_finds_nested_test_methods() -> None:
    from baps.plugins.language_python import PythonLanguagePlugin

    file = CodeFile(path="test_x.py", content=_TEST_PY)
    result = PythonLanguagePlugin().extract_tests(file)
    assert "test_method" in result


def test_extract_tests_none_returns_none_message() -> None:
    from baps.plugins.language_python import PythonLanguagePlugin

    src = "def foo():\n    pass\n"
    file = CodeFile(path="x.py", content=src)
    result = PythonLanguagePlugin().extract_tests(file)
    assert "none" in result.lower()


# ---------------------------------------------------------------------------
# PythonLanguagePlugin.extract_entity
# ---------------------------------------------------------------------------

_ENTITY_PY = """\
def greet(name: str) -> str:
    \"\"\"Return a greeting.\"\"\"
    return f"Hello, {name}"


class Animal:
    \"\"\"Base animal class.\"\"\"

    def speak(self) -> str:
        \"\"\"Make a sound.\"\"\"
        return ""
"""


def test_extract_entity_full_returns_function_body() -> None:
    from baps.plugins.language_python import PythonLanguagePlugin

    file = CodeFile(path="e.py", content=_ENTITY_PY)
    result = PythonLanguagePlugin().extract_entity(file, "greet", "full")
    assert "return f" in result
    assert "def greet" in result


def test_extract_entity_none_filter_returns_full_body() -> None:
    from baps.plugins.language_python import PythonLanguagePlugin

    file = CodeFile(path="e.py", content=_ENTITY_PY)
    result = PythonLanguagePlugin().extract_entity(file, "greet", None)
    assert "return f" in result


def test_extract_entity_api_returns_signature_only() -> None:
    from baps.plugins.language_python import PythonLanguagePlugin

    file = CodeFile(path="e.py", content=_ENTITY_PY)
    result = PythonLanguagePlugin().extract_entity(file, "greet", "api")
    assert "def greet(name: str) -> str:" in result
    assert "return f" not in result


def test_extract_entity_api_includes_docstring_first_line() -> None:
    from baps.plugins.language_python import PythonLanguagePlugin

    file = CodeFile(path="e.py", content=_ENTITY_PY)
    result = PythonLanguagePlugin().extract_entity(file, "greet", "api")
    assert "Return a greeting" in result


def test_extract_entity_class_full_returns_class_body() -> None:
    from baps.plugins.language_python import PythonLanguagePlugin

    file = CodeFile(path="e.py", content=_ENTITY_PY)
    result = PythonLanguagePlugin().extract_entity(file, "Animal", "full")
    assert "class Animal:" in result
    assert "def speak" in result


def test_extract_entity_class_api_returns_class_signature_and_methods() -> None:
    from baps.plugins.language_python import PythonLanguagePlugin

    file = CodeFile(path="e.py", content=_ENTITY_PY)
    result = PythonLanguagePlugin().extract_entity(file, "Animal", "api")
    assert "class Animal:" in result
    assert "def speak" in result
    assert "return" not in result


def test_extract_entity_not_found_lists_available() -> None:
    from baps.plugins.language_python import PythonLanguagePlugin

    file = CodeFile(path="e.py", content=_ENTITY_PY)
    result = PythonLanguagePlugin().extract_entity(file, "missing_fn", "full")
    assert "not found" in result
    assert "greet" in result
    assert "Animal" in result


def test_extract_entity_unknown_filter_returns_helpful_error() -> None:
    from baps.plugins.language_python import PythonLanguagePlugin

    file = CodeFile(path="e.py", content=_ENTITY_PY)
    result = PythonLanguagePlugin().extract_entity(file, "greet", "bogus")
    assert "Unknown filter" in result
    assert "bogus" in result
    assert "api" in result


# ---------------------------------------------------------------------------
# Rust extract_* delegate to Docker indexer
# ---------------------------------------------------------------------------


def _rust_mock(items: list) -> "MagicMock":
    import json
    from unittest.mock import MagicMock

    m = MagicMock()
    m.stdout = json.dumps({"items": items})
    m.returncode = 0
    return m


_FOO_ITEM = {
    "kind": "fn",
    "name": "foo",
    "pub": True,
    "signature": "pub fn foo ()",
    "doc": None,
    "is_test": False,
    "body_start": 1,
    "body_end": 1,
}

_TEST_FOO_ITEM = {
    "kind": "fn",
    "name": "test_foo",
    "pub": False,
    "signature": "fn test_foo ()",
    "doc": None,
    "is_test": True,
    "body_start": 2,
    "body_end": 2,
}


def test_rust_extract_api_returns_public_items() -> None:
    from unittest.mock import patch

    from baps.plugins.language_rust import RustLanguagePlugin

    file = CodeFile(path="lib.rs", content="pub fn foo() {}")
    with patch(
        "baps.plugins.language_rust.subprocess.run",
        return_value=_rust_mock([_FOO_ITEM]),
    ):
        result = RustLanguagePlugin().extract_api(file)
    assert "foo" in result


def test_rust_extract_tests_returns_test_items() -> None:
    from unittest.mock import patch

    from baps.plugins.language_rust import RustLanguagePlugin

    file = CodeFile(path="lib.rs", content="#[test]\nfn test_foo() {}")
    with patch(
        "baps.plugins.language_rust.subprocess.run",
        return_value=_rust_mock([_TEST_FOO_ITEM]),
    ):
        result = RustLanguagePlugin().extract_tests(file)
    assert "test_foo" in result


def test_rust_extract_entity_returns_entity_body() -> None:
    from unittest.mock import patch

    from baps.plugins.language_rust import RustLanguagePlugin

    file = CodeFile(path="lib.rs", content="pub fn foo() {}")
    with patch(
        "baps.plugins.language_rust.subprocess.run",
        return_value=_rust_mock([_FOO_ITEM]),
    ):
        result = RustLanguagePlugin().extract_entity(file, "foo", None)
    assert "foo" in result


def test_zig_extract_api_is_implemented() -> None:
    import json
    from unittest.mock import MagicMock, patch

    from baps.plugins.language_zig import ZigLanguagePlugin

    file = CodeFile(path="main.zig", content="pub fn foo() void {}")
    mock = MagicMock()
    mock.stdout = json.dumps(
        {
            "items": [
                {
                    "kind": "fn",
                    "name": "foo",
                    "pub": True,
                    "signature": "pub fn foo() void",
                    "doc": None,
                    "is_test": False,
                    "body_start": 1,
                    "body_end": 1,
                }
            ]
        }
    )
    with patch("baps.plugins.language_zig.subprocess.run", return_value=mock):
        result = ZigLanguagePlugin().extract_api(file)
    assert "foo" in result


def test_zig_extract_entity_is_implemented() -> None:
    import json
    from unittest.mock import MagicMock, patch

    from baps.plugins.language_zig import ZigLanguagePlugin

    file = CodeFile(path="main.zig", content="pub fn foo() void {}")
    mock = MagicMock()
    mock.stdout = json.dumps(
        {
            "items": [
                {
                    "kind": "fn",
                    "name": "foo",
                    "pub": True,
                    "signature": "pub fn foo() void",
                    "doc": None,
                    "is_test": False,
                    "body_start": 1,
                    "body_end": 1,
                }
            ]
        }
    )
    with patch("baps.plugins.language_zig.subprocess.run", return_value=mock):
        result = ZigLanguagePlugin().extract_entity(file, "foo", None)
    assert "foo" in result


# ---------------------------------------------------------------------------
# CodingProjectAdapter — list_modules
# ---------------------------------------------------------------------------


def test_coding_list_modules_no_filter_returns_paths_and_line_counts() -> None:
    from baps.adapters.coding_adapter import CodingProjectAdapter

    state = _coding_state([("src/foo.py", "x = 1\ny = 2\n")])
    result = CodingProjectAdapter().execute_create_game_research_tool(
        "list_modules", {}, state
    )
    assert "src/foo.py" in result
    assert "2 lines" in result


def test_coding_list_modules_no_artifact_returns_no_files() -> None:
    from baps.adapters.coding_adapter import CodingProjectAdapter

    state = State(
        northstar=NorthStar(artifacts=()),
        artifacts=(DocumentArtifact(id="doc", sections=()),),
    )
    result = CodingProjectAdapter().execute_create_game_research_tool(
        "list_modules", {}, state
    )
    assert "no files" in result.lower() or result == "(no files)"


def test_coding_list_modules_filter_api_includes_signature_stats() -> None:
    from baps.adapters.coding_adapter import CodingProjectAdapter

    src = "def foo():\n    pass\n"
    state = _coding_state([("src/a.py", src)])
    result = CodingProjectAdapter().execute_create_game_research_tool(
        "list_modules", {"filter": "api"}, state
    )
    assert "src/a.py" in result
    assert "signature" in result


def test_coding_list_modules_filter_tests_includes_test_count() -> None:
    from baps.adapters.coding_adapter import CodingProjectAdapter

    src = "def test_one(): pass\ndef test_two(): pass\n"
    state = _coding_state([("tests/test_a.py", src)])
    result = CodingProjectAdapter().execute_create_game_research_tool(
        "list_modules", {"filter": "tests"}, state
    )
    assert "tests/test_a.py" in result
    assert "tests" in result


def test_coding_list_modules_filter_full_still_returns_listing() -> None:
    from baps.adapters.coding_adapter import CodingProjectAdapter

    src = "x = 1\n"
    state = _coding_state([("src/a.py", src)])
    result = CodingProjectAdapter().execute_create_game_research_tool(
        "list_modules", {"filter": "full"}, state
    )
    assert "src/a.py" in result


def test_coding_list_modules_unknown_filter_returns_error() -> None:
    from baps.adapters.coding_adapter import CodingProjectAdapter

    state = _coding_state([("src/a.py", "x = 1\n")])
    result = CodingProjectAdapter().execute_create_game_research_tool(
        "list_modules", {"filter": "bogus"}, state
    )
    assert "Unknown filter" in result
    assert "bogus" in result
    assert "api" in result


# ---------------------------------------------------------------------------
# CodingProjectAdapter — fetch_module
# ---------------------------------------------------------------------------


def test_coding_fetch_module_no_filter_returns_path_and_count() -> None:
    from baps.adapters.coding_adapter import CodingProjectAdapter

    state = _coding_state([("src/a.py", "x = 1\ny = 2\n")])
    result = CodingProjectAdapter().execute_create_game_research_tool(
        "fetch_module", {"module_id": "src/a.py"}, state
    )
    assert "src/a.py" in result
    assert "2 lines" in result


def test_coding_fetch_module_full_returns_file_content() -> None:
    from baps.adapters.coding_adapter import CodingProjectAdapter

    state = _coding_state([("src/a.py", "def foo(): pass\n")])
    result = CodingProjectAdapter().execute_create_game_research_tool(
        "fetch_module", {"module_id": "src/a.py", "filter": "full"}, state
    )
    assert "def foo" in result


def test_coding_fetch_module_api_returns_signature_surface() -> None:
    from baps.adapters.coding_adapter import CodingProjectAdapter

    src = 'def bar(x: int) -> str:\n    """Return bar."""\n    return str(x)\n'
    state = _coding_state([("src/a.py", src)])
    result = CodingProjectAdapter().execute_create_game_research_tool(
        "fetch_module", {"module_id": "src/a.py", "filter": "api"}, state
    )
    assert "def bar" in result
    assert "Return bar" in result
    assert "return str(x)" not in result


def test_coding_fetch_module_tests_returns_test_names() -> None:
    from baps.adapters.coding_adapter import CodingProjectAdapter

    src = "def test_it(): pass\n"
    state = _coding_state([("tests/test_a.py", src)])
    result = CodingProjectAdapter().execute_create_game_research_tool(
        "fetch_module", {"module_id": "tests/test_a.py", "filter": "tests"}, state
    )
    assert "test_it" in result


def test_coding_fetch_module_not_found_lists_available() -> None:
    from baps.adapters.coding_adapter import CodingProjectAdapter

    state = _coding_state([("src/a.py", "x = 1\n")])
    result = CodingProjectAdapter().execute_create_game_research_tool(
        "fetch_module", {"module_id": "src/missing.py"}, state
    )
    assert "not found" in result.lower()
    assert "src/a.py" in result


def test_coding_fetch_module_unknown_filter_returns_error() -> None:
    from baps.adapters.coding_adapter import CodingProjectAdapter

    state = _coding_state([("src/a.py", "x = 1\n")])
    result = CodingProjectAdapter().execute_create_game_research_tool(
        "fetch_module", {"module_id": "src/a.py", "filter": "bogus"}, state
    )
    assert "Unknown filter" in result


# ---------------------------------------------------------------------------
# CodingProjectAdapter — fetch_entity
# ---------------------------------------------------------------------------


def test_coding_fetch_entity_full_returns_function_body() -> None:
    from baps.adapters.coding_adapter import CodingProjectAdapter

    src = "def greet(name: str) -> str:\n    return f'Hi {name}'\n"
    state = _coding_state([("src/a.py", src)])
    result = CodingProjectAdapter().execute_create_game_research_tool(
        "fetch_entity", {"module_id": "src/a.py", "entity_id": "greet"}, state
    )
    assert "def greet" in result
    assert "Hi {name}" in result


def test_coding_fetch_entity_api_returns_signature_only() -> None:
    from baps.adapters.coding_adapter import CodingProjectAdapter

    src = 'def greet(name: str) -> str:\n    """Greet."""\n    return f\'Hi {name}\'\n'
    state = _coding_state([("src/a.py", src)])
    result = CodingProjectAdapter().execute_create_game_research_tool(
        "fetch_entity",
        {"module_id": "src/a.py", "entity_id": "greet", "filter": "api"},
        state,
    )
    assert "def greet" in result
    assert "return f" not in result


def test_coding_fetch_entity_unknown_entity_lists_available() -> None:
    from baps.adapters.coding_adapter import CodingProjectAdapter

    src = "def real_fn(): pass\n"
    state = _coding_state([("src/a.py", src)])
    result = CodingProjectAdapter().execute_create_game_research_tool(
        "fetch_entity", {"module_id": "src/a.py", "entity_id": "ghost"}, state
    )
    assert "not found" in result
    assert "real_fn" in result


def test_coding_fetch_entity_unknown_module_returns_error() -> None:
    from baps.adapters.coding_adapter import CodingProjectAdapter

    state = _coding_state([("src/a.py", "def fn(): pass\n")])
    result = CodingProjectAdapter().execute_create_game_research_tool(
        "fetch_entity", {"module_id": "src/missing.py", "entity_id": "fn"}, state
    )
    assert "not found" in result.lower()


# ---------------------------------------------------------------------------
# DocumentProjectAdapter — list_modules
# ---------------------------------------------------------------------------


def test_document_list_modules_no_filter_lists_section_titles() -> None:
    from baps.adapters.document_adapter import DocumentProjectAdapter

    state = _document_state([("Intro", "Hello world. More text.")])
    result = DocumentProjectAdapter().execute_create_game_research_tool(
        "list_modules", {}, state
    )
    assert "Intro" in result
    assert "words" in result


def test_document_list_modules_summary_filter_includesfirst_sentence() -> None:
    from baps.adapters.document_adapter import DocumentProjectAdapter

    state = _document_state([("Overview", "First sentence. Second sentence.")])
    result = DocumentProjectAdapter().execute_create_game_research_tool(
        "list_modules", {"filter": "summary"}, state
    )
    assert "Overview" in result
    assert "First sentence." in result


def test_document_list_modules_unknown_filter_returns_error() -> None:
    from baps.adapters.document_adapter import DocumentProjectAdapter

    state = _document_state([("Intro", "Body.")])
    result = DocumentProjectAdapter().execute_create_game_research_tool(
        "list_modules", {"filter": "bogus"}, state
    )
    assert "Unknown filter" in result
    assert "bogus" in result


def test_document_list_modules_no_sections_returns_empty_message() -> None:
    from baps.adapters.document_adapter import DocumentProjectAdapter

    state = _document_state([])
    result = DocumentProjectAdapter().execute_create_game_research_tool(
        "list_modules", {}, state
    )
    assert "no sections" in result.lower() or result == "(no sections)"


# ---------------------------------------------------------------------------
# DocumentProjectAdapter — fetch_module
# ---------------------------------------------------------------------------


def test_document_fetch_module_no_filter_returns_title_and_word_count() -> None:
    from baps.adapters.document_adapter import DocumentProjectAdapter

    state = _document_state([("Intro", "Hello world today.")])
    result = DocumentProjectAdapter().execute_create_game_research_tool(
        "fetch_module", {"module_id": "Intro"}, state
    )
    assert "Intro" in result
    assert "words" in result


def test_document_fetch_module_summary_filter_returns_first_paragraph() -> None:
    from baps.adapters.document_adapter import DocumentProjectAdapter

    state = _document_state([("Intro", "First paragraph.\n\nSecond paragraph.")])
    result = DocumentProjectAdapter().execute_create_game_research_tool(
        "fetch_module", {"module_id": "Intro", "filter": "summary"}, state
    )
    assert "First paragraph" in result
    assert "Second paragraph" not in result


def test_document_fetch_module_full_returns_complete_body() -> None:
    from baps.adapters.document_adapter import DocumentProjectAdapter

    state = _document_state([("Intro", "Full body content here.")])
    result = DocumentProjectAdapter().execute_create_game_research_tool(
        "fetch_module", {"module_id": "Intro", "filter": "full"}, state
    )
    assert "Full body content here." in result


def test_document_fetch_module_not_found_lists_available() -> None:
    from baps.adapters.document_adapter import DocumentProjectAdapter

    state = _document_state([("Intro", "Body.")])
    result = DocumentProjectAdapter().execute_create_game_research_tool(
        "fetch_module", {"module_id": "Missing"}, state
    )
    assert "not found" in result.lower()
    assert "Intro" in result


def test_document_fetch_module_unknown_filter_returns_error() -> None:
    from baps.adapters.document_adapter import DocumentProjectAdapter

    state = _document_state([("Intro", "Body.")])
    result = DocumentProjectAdapter().execute_create_game_research_tool(
        "fetch_module", {"module_id": "Intro", "filter": "bogus"}, state
    )
    assert "Unknown filter" in result


# ---------------------------------------------------------------------------
# DocumentProjectAdapter — fetch_entity
# ---------------------------------------------------------------------------


def test_document_fetch_entity_returns_not_supported_error() -> None:
    from baps.adapters.document_adapter import DocumentProjectAdapter

    state = _document_state([("Intro", "Body.")])
    result = DocumentProjectAdapter().execute_create_game_research_tool(
        "fetch_entity", {"module_id": "Intro", "entity_id": "anything"}, state
    )
    assert "tool_error" in result
    assert "not supported" in result


# ---------------------------------------------------------------------------
# Unknown filter error message format
# ---------------------------------------------------------------------------


def test_unknown_filter_message_includes_available_filters() -> None:
    from baps.adapters.document_adapter import DocumentProjectAdapter

    state = _document_state([("Intro", "Body.")])
    result = DocumentProjectAdapter().execute_create_game_research_tool(
        "list_modules", {"filter": "xyz"}, state
    )
    assert "summary" in result
    assert "full" in result


def test_coding_unknown_filter_message_includes_available_filters() -> None:
    from baps.adapters.coding_adapter import CodingProjectAdapter

    state = _coding_state([("src/a.py", "x = 1\n")])
    result = CodingProjectAdapter().execute_create_game_research_tool(
        "list_modules", {"filter": "xyz"}, state
    )
    assert "api" in result
    assert "full" in result


# ---------------------------------------------------------------------------
# Zig adapter uses plugin-specific filters in tool schema
# ---------------------------------------------------------------------------


def test_coding_adapter_zig_build_tools_filter_enum_includes_tests() -> None:
    from baps.adapters.coding_adapter import CodingProjectAdapter

    state = _coding_state([("src/main.zig", "// code\n")], language="zig")
    tools = CodingProjectAdapter().build_create_game_research_tools(state)
    list_tool = next(t for t in tools if t.name == "list_modules")
    filter_enum = (
        list_tool.parameters.get("properties", {}).get("filter", {}).get("enum", [])
    )
    assert "tests" in filter_enum
    assert "api" in filter_enum
    assert "full" in filter_enum


# ---------------------------------------------------------------------------
# Backward-compat: fetch_section / fetch_file still work via execute
# ---------------------------------------------------------------------------


def test_coding_execute_fetch_file_still_works() -> None:
    from baps.adapters.coding_adapter import CodingProjectAdapter

    state = _coding_state([("src/a.py", "def fn(): pass\n")])
    result = CodingProjectAdapter().execute_create_game_research_tool(
        "fetch_file", {"path": "src/a.py"}, state
    )
    assert "def fn" in result


def test_document_execute_fetch_section_still_works() -> None:
    from baps.adapters.document_adapter import DocumentProjectAdapter

    state = _document_state([("Intro", "Original body.")])
    result = DocumentProjectAdapter().execute_create_game_research_tool(
        "fetch_section", {"title": "Intro"}, state
    )
    assert result == "Original body."
