# Tags show up on notes I never tagged

Steps to reproduce:

1. Create a note "Groceries" and tag it `shopping`.
2. Create another note "Meeting notes" without any tags.

The new note already has the `shopping` tag, and searching by that tag returns both
notes. It looks like every note created without explicit tags shares one tag list.

Expected: a new note starts with no tags, and tagging one note never changes another.
