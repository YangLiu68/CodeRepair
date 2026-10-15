# [security] safe_join lets paths escape into sibling directories

`safe_join` is supposed to keep user-supplied names inside the base directory, but a
name that walks up and back into a *sibling* directory whose name starts with the same
prefix is accepted:

    safe_join("/srv/data", "../data-backup/secrets.txt")
    # returns "/srv/data-backup/secrets.txt" instead of raising UnsafePathError

`FileStore.read_text("../data-backup/secrets.txt")` can therefore read files outside the
store root. Plain `../etc/passwd` is correctly rejected.

Severity: high (path traversal, CWE-22).
