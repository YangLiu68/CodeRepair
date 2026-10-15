# Pagination skips the first page of results

When I paginate a list, page 1 doesn't contain the first items. With 25 items and the
default page size, `paginate(items, 1)` gives me items 10-19, and the last page
(page 3) comes back empty.

Expected: page 1 -> items 0-9, page 3 -> items 20-24.

pager 0.1.0, Python 3.12
