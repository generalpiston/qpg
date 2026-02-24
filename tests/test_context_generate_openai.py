from __future__ import annotations

import json
from typing import Any

from qpg.context_generate import _call_openai_chat


class _FakeResponse:
    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(
            {
                "choices": [
                    {
                        "message": {
                            "content": '{"decision":"generate","context":"ok"}',
                        }
                    }
                ]
            }
        ).encode("utf-8")


def test_call_openai_chat_omits_temperature_for_gpt_5_models(monkeypatch) -> None:
    captured: dict[str, Any] = {}

    def fake_urlopen(req, timeout: int):
        captured["timeout"] = timeout
        captured["url"] = req.full_url
        captured["payload"] = json.loads(req.data.decode("utf-8"))
        return _FakeResponse()

    monkeypatch.setattr("qpg.context_generate.request.urlopen", fake_urlopen)

    text = _call_openai_chat(
        api_key="test-key",
        model="nano-gpt-5",
        base_url="https://api.openai.com/v1",
        prompt="prompt",
    )

    assert text == '{"decision":"generate","context":"ok"}'
    assert captured["timeout"] == 30
    assert captured["url"] == "https://api.openai.com/v1/chat/completions"
    assert captured["payload"]["model"] == "nano-gpt-5"
    assert "temperature" not in captured["payload"]
