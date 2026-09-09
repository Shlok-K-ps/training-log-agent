"""Fail-closed supplement scheduling safeguards.

The authoritative prohibited list changes annually. Unknown regimens are never
scheduled unless a team operator separately allowlists the exact name, dose,
unit and timing in deployment configuration. This deny list is a second line of
defence, not a replacement for the WADA list or professional review.
"""

from __future__ import annotations

import re

WADA_LIST_VERSION = "2026"
WADA_LIST_URL = (
    "https://www.wada-ama.org/sites/default/files/2025-09/"
    "2026list_en_final_clean_september_2025.pdf"
)

# Named S1 examples most likely to be presented as supplements. Exact-regimen
# allowlisting below means substances absent from this set still fail closed.
PROHIBITED_TERMS = {
    "andarine",
    "enobosarm",
    "ostarine",
    "lgd 4033",
    "ligandrol",
    "rad140",
    "rad 140",
    "s 23",
    "yk 11",
    "sarm",
    "sarms",
}


def prohibited_match(name: str) -> str | None:
    normalized = re.sub(r"[^a-z0-9]+", " ", name.casefold()).strip()
    compact = normalized.replace(" ", "")
    for term in PROHIBITED_TERMS:
        term_normalized = re.sub(r"[^a-z0-9]+", " ", term).strip()
        if term_normalized in normalized or term_normalized.replace(" ", "") in compact:
            return term
    return None
