"""Integration tests for RustLanguagePlugin extract_* methods."""

import json
from unittest.mock import MagicMock, patch

import pytest

from baps.plugins.language_rust import RustLanguagePlugin
from baps.state.state import CodeFile

_RUST_FIXTURE = """\
/// Returns the word frequency map.
pub fn word_frequency(text: &str) -> Vec<(String, usize)> {
    let mut map = std::collections::HashMap::new();
    for word in text.split_whitespace() {
        *map.entry(word.to_string()).or_insert(0) += 1;
    }
    map.into_iter().collect()
}

pub struct WordCounter {
    total: usize,
}

fn private_helper(x: i32) -> i32 {
    x * 2
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_word_frequency() {
        let result = word_frequency("hello world hello");
        assert_eq!(result.len(), 2);
    }
}
"""

_FIXTURE_INDEX = {
    "items": [
        {
            "kind": "fn",
            "name": "word_frequency",
            "pub": True,
            "signature": "pub fn word_frequency (text : & str) -> Vec < (String , usize) >",
            "doc": "Returns the word frequency map.",
            "is_test": False,
            "body_start": 1,
            "body_end": 8,
        },
        {
            "kind": "struct",
            "name": "WordCounter",
            "pub": True,
            "signature": "pub struct WordCounter",
            "doc": None,
            "is_test": False,
            "body_start": 10,
            "body_end": 12,
        },
        {
            "kind": "fn",
            "name": "private_helper",
            "pub": False,
            "signature": "fn private_helper (x : i32) -> i32",
            "doc": None,
            "is_test": False,
            "body_start": 14,
            "body_end": 16,
        },
        {
            "kind": "fn",
            "name": "test_word_frequency",
            "pub": False,
            "signature": "fn test_word_frequency ()",
            "doc": None,
            "is_test": True,
            "body_start": 22,
            "body_end": 26,
        },
    ]
}


def _make_docker_mock():
    mock = MagicMock()
    mock.stdout = json.dumps(_FIXTURE_INDEX)
    mock.returncode = 0
    return mock


@pytest.fixture
def plugin():
    return RustLanguagePlugin()


@pytest.fixture
def fixture_file():
    return CodeFile(path="lib.rs", content=_RUST_FIXTURE)


@pytest.fixture(autouse=True)
def mock_docker(monkeypatch):
    with patch(
        "baps.plugins.language_rust.subprocess.run", return_value=_make_docker_mock()
    ) as m:
        yield m


def test_extract_api_pub_items(plugin, fixture_file):
    result = plugin.extract_api(fixture_file)
    assert "word_frequency" in result
    assert "WordCounter" in result
    assert "private_helper" not in result


def test_extract_api_missing_doc(plugin, fixture_file):
    result = plugin.extract_api(fixture_file)
    lines = result.splitlines()
    struct_idx = next(i for i, line in enumerate(lines) if "WordCounter" in line)
    assert "MISSING" in lines[struct_idx + 1]
    fn_idx = next(i for i, line in enumerate(lines) if "word_frequency" in line)
    assert "Returns the word frequency map." in lines[fn_idx + 1]


def test_extract_tests(plugin, fixture_file):
    result = plugin.extract_tests(fixture_file)
    assert "Tests in lib.rs" in result
    assert "test_word_frequency" in result


def test_extract_entity_full(plugin, fixture_file):
    result = plugin.extract_entity(fixture_file, "word_frequency", filter="full")
    assert "pub fn word_frequency" in result
    assert "map.into_iter().collect()" in result


def test_extract_entity_api(plugin, fixture_file):
    result = plugin.extract_entity(fixture_file, "word_frequency", filter="api")
    assert "fn word_frequency" in result
    assert "HashMap" not in result


def test_extract_entity_not_found(plugin, fixture_file):
    result = plugin.extract_entity(fixture_file, "nonexistent_fn", filter="full")
    assert "nonexistent_fn" in result
    assert "word_frequency" in result  # available names listed


def test_supported_filters(plugin):
    assert plugin.supported_filters() == ["api", "tests", "full"]
