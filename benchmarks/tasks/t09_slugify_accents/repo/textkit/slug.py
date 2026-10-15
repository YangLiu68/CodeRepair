"""URL slug generation."""
from __future__ import annotations

import re
import unicodedata

_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def slugify(text: str, max_length: int = 60) -> str:
    """Make a lowercase ASCII slug: ``"Café Crème!"`` -> ``"cafe-creme"``.

    Accented letters are transliterated to their unaccented form, runs of other
    characters become a single hyphen, and the slug never starts or ends with a
    hyphen.
    """
    ascii_text = text.encode("ascii", "ignore").decode("ascii")
    ascii_text = unicodedata.normalize("NFKD", ascii_text)
    slug = _NON_ALNUM.sub("-", ascii_text.lower()).strip("-")
    if len(slug) > max_length:
        slug = slug[:max_length].rstrip("-")
    return slug
