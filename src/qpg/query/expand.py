from __future__ import annotations

import re

SYNONYMS = {
    "payment": ["payments", "billing", "charge"],
    "refund": ["refunds", "reversal", "chargeback"],
    "subscription": ["subscriptions", "plan", "renewal"],
    "status": ["state", "lifecycle"],
    "order": ["orders", "purchase"],
}


def expand_query(query: str) -> list[str]:
    tokens = re.findall(r"[A-Za-z0-9_]+", query.lower())
    expanded = set(tokens)

    for token in tokens:
        if token.endswith("s") and len(token) > 3:
            expanded.add(token[:-1])
        else:
            expanded.add(f"{token}s")

        for synonym in SYNONYMS.get(token, []):
            expanded.add(synonym)

    ordered = sorted(expanded)
    if not ordered:
        return [query]

    return [query, " ".join(ordered)]
