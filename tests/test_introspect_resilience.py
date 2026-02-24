from __future__ import annotations

from typing import Any

import qpg.schema.introspect as introspect_mod


def test_introspect_schema_skips_failed_section_and_collects_warning(monkeypatch) -> None:
    def fake_fetch_all(_: Any, sql: str) -> list[dict[str, Any]]:
        compact = " ".join(sql.split())
        if "FROM pg_proc" in compact:
            raise RuntimeError('"array_concat_agg" is an aggregate function')
        return []

    monkeypatch.setattr(introspect_mod, "fetch_all", fake_fetch_all)

    bundle = introspect_mod.introspect_schema(object(), include_functions=True)

    assert bundle.objects == []
    assert bundle.columns == []
    assert bundle.constraints == []
    assert bundle.indexes == []
    assert bundle.dependencies == []
    assert any("functions:" in warning for warning in bundle.warnings)
    assert any("aggregate function" in warning for warning in bundle.warnings)
