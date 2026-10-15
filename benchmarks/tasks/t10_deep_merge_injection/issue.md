# Nested config sections lose keys when a layer overrides a deeper value

With `defaults.json`:

```json
{"db": {"pool": {"min": 1, "max": 10}, "host": "a"}}
```

and `production.json`:

```json
{"db": {"pool": {"max": 20}}}
```

the merged config is `{"db": {"pool": {"max": 20}, "host": "a"}}` - `pool.min` is gone.
One level of nesting works; two or more do not. `tests/test_merge.py::test_merge_two_levels_deep`
shows the problem.
