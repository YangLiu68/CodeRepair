"""Invoice numbers: ``<prefix>-<year>-<sequence>``, the sequence restarting every year.

Many jurisdictions require gapless invoice numbering per fiscal year, so numbers are only
assigned when an invoice is finalized. The year is the issuer's local calendar year: the
numberer is configured with the issuer's UTC offset and converts the issue time to it.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone


class InvoiceNumberer:
    def __init__(self, prefix: str = "INV", utc_offset_hours: int = 0, width: int = 5) -> None:
        if not prefix.isalnum():
            raise ValueError("prefix must be alphanumeric")
        self.prefix = prefix
        self.zone = timezone(timedelta(hours=utc_offset_hours))
        self.width = width
        self._last: dict[int, int] = {}

    def year_of(self, issued_at: datetime) -> int:
        if issued_at.tzinfo is None:
            raise ValueError("issue times must be timezone-aware")
        return issued_at.astimezone(self.zone).year

    def next_number(self, issued_at: datetime) -> str:
        year = self.year_of(issued_at)
        sequence = self._last.get(year, 0) + 1
        self._last[year] = sequence
        return f"{self.prefix}-{year}-{sequence:0{self.width}d}"

    def peek(self, issued_at: datetime) -> str:
        """The number ``next_number`` would return, without using it."""
        year = self.year_of(issued_at)
        return f"{self.prefix}-{year}-{self._last.get(year, 0) + 1:0{self.width}d}"
