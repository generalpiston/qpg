from __future__ import annotations

from collections import defaultdict
from typing import Any


def reciprocal_rank_fusion(
    ranked_lists: list[list[dict[str, Any]]],
    *,
    k: int = 60,
    top_rank_bonus: float = 0.02,
) -> list[dict[str, Any]]:
    if k <= 0:
        raise ValueError("k must be positive")

    merged: dict[str, dict[str, Any]] = {}
    scores: defaultdict[str, float] = defaultdict(float)

    for ranked in ranked_lists:
        for rank, row in enumerate(ranked, start=1):
            object_id = str(row["object_id"])
            scores[object_id] += 1.0 / (k + rank)
            if rank == 1:
                scores[object_id] += top_rank_bonus

            if object_id not in merged:
                merged[object_id] = dict(row)

    result = []
    for object_id, row in merged.items():
        fused = dict(row)
        fused["rrf_score"] = scores[object_id]
        result.append(fused)

    result.sort(key=lambda item: item["rrf_score"], reverse=True)
    return result
