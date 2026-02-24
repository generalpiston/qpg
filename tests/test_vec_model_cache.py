from __future__ import annotations

from pathlib import Path

import qpg.index.vec as vec_mod


def test_embedder_caches_model_into_models_dir(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setattr(vec_mod, "_EMBEDDER", None)

    def fake_snapshot_download(*, repo_id: str, local_dir: str) -> str:
        path = Path(local_dir)
        path.mkdir(parents=True, exist_ok=True)
        (path / "config.json").write_text('{"ok": true}', encoding="utf-8")
        return str(path)

    monkeypatch.setattr(vec_mod, "snapshot_download", fake_snapshot_download)
    model_dir = vec_mod.init_vector_model()

    assert model_dir == tmp_path / "cache" / "qpg" / "models" / vec_mod.CODE_MODEL_DIRNAME
    assert (model_dir / "config.json").exists()


def test_embed_text_requires_initialized_model(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setattr(vec_mod, "_EMBEDDER", None)

    try:
        vec_mod.embed_text("orders table")
    except vec_mod.VectorModelNotInitializedError as exc:
        assert "qpg init" in str(exc)
    else:
        raise AssertionError("expected VectorModelNotInitializedError")
