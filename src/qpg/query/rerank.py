from __future__ import annotations

import json
import os
import subprocess
from typing import Any


class RerankHookError(RuntimeError):
    pass


def rerank_with_hook(query: str, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    hook = os.environ.get("QPG_RERANK_HOOK")
    if not hook:
        return rows

    payload = {"query": query, "results": rows}
    proc = subprocess.run(
        [hook],
        input=json.dumps(payload).encode("utf-8"),
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RerankHookError(proc.stderr.decode("utf-8", errors="replace").strip())

    try:
        output = json.loads(proc.stdout.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise RerankHookError("rerank hook returned invalid JSON") from exc

    if not isinstance(output, list):
        raise RerankHookError("rerank hook output must be a JSON list")

    by_id = {row["object_id"]: row for row in rows}
    reordered: list[dict[str, Any]] = []
    seen: set[str] = set()

    for object_id in output:
        key = str(object_id)
        if key in by_id:
            reordered.append(by_id[key])
            seen.add(key)

    for row in rows:
        key = str(row["object_id"])
        if key not in seen:
            reordered.append(row)
    return reordered
