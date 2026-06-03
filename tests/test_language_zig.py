"""Tests for ZigLanguagePlugin extract_* methods."""

import json
from unittest.mock import MagicMock, patch

import pytest

from baps.plugins.language_zig import ZigLanguagePlugin
from baps.state.state import CodeFile

_ZIG_FIXTURE = """\
/// Counts words in the input slice.
pub fn wordCount(text: []const u8) usize {
    var count: usize = 0;
    for (text) |c| {
        if (c == ' ') count += 1;
    }
    return count + 1;
}

pub const WordPair = struct {
    word: []const u8,
    freq: usize,
};

fn privateHelper(x: u32) u32 {
    return x * 2;
}

test "wordCount basic" {
    const result = wordCount("hello world");
    _ = result;
}
"""

_FIXTURE_INDEX = {
    "items": [
        {
            "kind": "fn",
            "name": "wordCount",
            "pub": True,
            "signature": "pub fn wordCount(text: []const u8) usize",
            "doc": "Counts words in the input slice.",
            "is_test": False,
            "body_start": 2,
            "body_end": 8,
        },
        {
            "kind": "struct",
            "name": "WordPair",
            "pub": True,
            "signature": "pub const WordPair = struct",
            "doc": None,
            "is_test": False,
            "body_start": 10,
            "body_end": 13,
        },
        {
            "kind": "fn",
            "name": "privateHelper",
            "pub": False,
            "signature": "fn privateHelper(x: u32) u32",
            "doc": None,
            "is_test": False,
            "body_start": 16,
            "body_end": 18,
        },
        {
            "kind": "fn",
            "name": "wordCount basic",
            "pub": False,
            "signature": 'test "wordCount basic"',
            "doc": None,
            "is_test": True,
            "body_start": 20,
            "body_end": 23,
        },
    ]
}


def _make_mock():
    m = MagicMock()
    m.stdout = json.dumps(_FIXTURE_INDEX)
    m.returncode = 0
    return m


@pytest.fixture
def plugin():
    return ZigLanguagePlugin()


@pytest.fixture
def fixture_file():
    return CodeFile(path="main.zig", content=_ZIG_FIXTURE)


@pytest.fixture(autouse=True)
def mock_docker(monkeypatch):
    with patch("baps.plugins.language_zig.subprocess.run", return_value=_make_mock()) as m:
        yield m


def test_extract_api_pub_items(plugin, fixture_file):
    result = plugin.extract_api(fixture_file)
    assert "wordCount" in result
    assert "WordPair" in result
    assert "privateHelper" not in result


def test_extract_api_missing_doc(plugin, fixture_file):
    result = plugin.extract_api(fixture_file)
    lines = result.splitlines()
    struct_idx = next(i for i, line in enumerate(lines) if "WordPair" in line)
    assert "MISSING" in lines[struct_idx + 1]
    fn_idx = next(i for i, line in enumerate(lines) if "wordCount" in line and "test" not in line)
    assert "Counts words" in lines[fn_idx + 1]


def test_extract_tests(plugin, fixture_file):
    result = plugin.extract_tests(fixture_file)
    assert "Tests in main.zig" in result
    assert "wordCount basic" in result


def test_extract_entity_full(plugin, fixture_file):
    result = plugin.extract_entity(fixture_file, "wordCount", filter="full")
    assert "pub fn wordCount" in result
    assert "return count + 1" in result


def test_extract_entity_api(plugin, fixture_file):
    result = plugin.extract_entity(fixture_file, "wordCount", filter="api")
    assert "fn wordCount" in result
    assert "return count" not in result


def test_extract_entity_not_found(plugin, fixture_file):
    result = plugin.extract_entity(fixture_file, "noSuchFn", filter="full")
    assert "noSuchFn" in result
    assert "wordCount" in result


def test_supported_filters(plugin):
    assert plugin.supported_filters() == ["api", "tests", "full"]
