from baps.role_output_parsing import get_dict, get_non_empty_string, parse_json_object


def test_parse_json_object_valid_object() -> None:
    parsed = parse_json_object('{"k":"v","n":1}')
    assert parsed == {"k": "v", "n": 1}


def test_parse_json_object_malformed_json_returns_none() -> None:
    assert parse_json_object('{"k":"v"') is None


def test_parse_json_object_non_object_returns_none() -> None:
    assert parse_json_object('["a","b"]') is None
    assert parse_json_object('"text"') is None


def test_get_non_empty_string_returns_trimmed_value() -> None:
    data = {"summary": "  hello  "}
    assert get_non_empty_string(data, "summary") == "hello"


def test_get_non_empty_string_returns_none_for_missing_or_empty() -> None:
    data = {"summary": "   "}
    assert get_non_empty_string(data, "summary") is None
    assert get_non_empty_string(data, "missing") is None


def test_get_dict_returns_object_only() -> None:
    data = {"payload": {"k": "v"}, "not_payload": "x"}
    assert get_dict(data, "payload") == {"k": "v"}
    assert get_dict(data, "not_payload") is None
    assert get_dict(data, "missing") is None
