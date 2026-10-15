# total_covered() under-reports coverage for unsorted input

`total_covered([(5, 8), (1, 6)])` returns `3`, but the union is `[1, 8]`, which has
length 7.

Failing test output:

```
tests/test_ops.py::test_total_covered_unsorted_input FAILED

>       assert total_covered([(5, 8), (1, 6)]) == 7
E       assert 3 == 7
```

It only seems to happen when the intervals are not already sorted by start.
