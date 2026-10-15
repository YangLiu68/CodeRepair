from confmerge import deep_merge


def test_override_scalar():
    assert deep_merge({"debug": False, "name": "x"}, {"debug": True}) == {"debug": True, "name": "x"}


def test_merge_one_level():
    base = {"db": {"host": "a", "port": 1}}
    assert deep_merge(base, {"db": {"port": 2}}) == {"db": {"host": "a", "port": 2}}


def test_inputs_not_modified():
    base = {"db": {"host": "a"}}
    override = {"db": {"port": 2}}
    deep_merge(base, override)
    assert base == {"db": {"host": "a"}}
    assert override == {"db": {"port": 2}}


def test_merge_two_levels_deep():
    base = {"db": {"pool": {"min": 1, "max": 10}, "host": "a"}}
    override = {"db": {"pool": {"max": 20}}}
    assert deep_merge(base, override) == {"db": {"pool": {"min": 1, "max": 20}, "host": "a"}}
