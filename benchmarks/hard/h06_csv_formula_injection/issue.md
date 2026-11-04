# Security: CSV export still allows formula injection (CWE-1236)

Reported by an external researcher through our disclosure program.

Last quarter we fixed `=` payloads in the finance CSV export, but spreadsheet applications also
evaluate cells that start with `+`, `-` or `@`, and payloads prefixed with a tab or a carriage
return. A customer who names their company `@SUM(1+9)*cmd|' /C calc'!A0` gets that evaluated
when finance opens the monthly export in Excel. Plan and line descriptions can be influenced by
customers too.

Please neutralise all of these (OWASP: prefix the cell with a single quote). Finance uses the
export for reconciliation, so it has to stay usable for them.
