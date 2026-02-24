from qpg.query.rrf import reciprocal_rank_fusion


def test_rrf_prefers_items_present_in_multiple_lists() -> None:
    list_a = [
        {"object_id": "a", "score": 0.9},
        {"object_id": "b", "score": 0.8},
        {"object_id": "c", "score": 0.7},
    ]
    list_b = [
        {"object_id": "b", "score": 0.95},
        {"object_id": "x", "score": 0.8},
    ]

    fused = reciprocal_rank_fusion([list_a, list_b], k=60)
    ordered_ids = [row["object_id"] for row in fused]

    assert ordered_ids[0] == "b"
    assert "a" in ordered_ids
    assert "x" in ordered_ids


def test_rrf_rejects_invalid_k() -> None:
    try:
        reciprocal_rank_fusion([], k=0)
    except ValueError as exc:
        assert "positive" in str(exc)
    else:
        raise AssertionError("expected ValueError")
