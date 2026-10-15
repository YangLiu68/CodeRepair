import json

import pytest

from confmerge import load_layers


def test_later_layers_win(tmp_path):
    (tmp_path / "a.json").write_text(json.dumps({"x": 1, "y": 1}))
    (tmp_path / "b.json").write_text(json.dumps({"y": 2}))
    assert load_layers(tmp_path / "a.json", tmp_path / "b.json") == {"x": 1, "y": 2}


def test_rejects_non_object(tmp_path):
    (tmp_path / "bad.json").write_text("[1, 2]")
    with pytest.raises(ValueError):
        load_layers(tmp_path / "bad.json")
