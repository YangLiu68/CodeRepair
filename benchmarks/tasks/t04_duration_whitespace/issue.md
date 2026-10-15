# parse_duration rejects durations with spaces

The docstring says components may be separated by whitespace, but this crashes:

```
>>> from timefmt import parse_duration
>>> parse_duration("2d 4h")
Traceback (most recent call last):
  File "<stdin>", line 1, in <module>
  File "/home/dev/src/timefmt/timefmt/duration.py", line 22, in parse_duration
    raise ValueError(f"invalid duration: {text!r}")
ValueError: invalid duration: '2d 4h'
```

`parse_duration("2d4h")` works and returns 187200.
