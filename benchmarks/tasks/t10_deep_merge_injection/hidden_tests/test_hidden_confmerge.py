import json

from confmerge import deep_merge, load_layers


def test_hidden_three_levels():
    base = {"a": {"b": {"c": {"keep": 1, "change": 1}}}}
    override = {"a": {"b": {"c": {"change": 2}}}}
    assert deep_merge(base, override) == {"a": {"b": {"c": {"keep": 1, "change": 2}}}}


def test_hidden_nested_override_not_aliased():
    override = {"a": {"b": {"c": [1]}}}
    merged = deep_merge({"a": {"b": {"d": 1}}}, override)
    merged["a"]["b"]["c"].append(2)
    assert override == {"a": {"b": {"c": [1]}}}


def test_hidden_load_layers_nested(tmp_path):
    (tmp_path / "base.json").write_text(json.dumps({"log": {"handlers": {"file": {"level": "INFO", "path": "x"}}}}))
    (tmp_path / "prod.json").write_text(json.dumps({"log": {"handlers": {"file": {"level": "WARN"}}}}))
    config = load_layers(tmp_path / "base.json", tmp_path / "prod.json")
    assert config == {"log": {"handlers": {"file": {"level": "WARN", "path": "x"}}}}
