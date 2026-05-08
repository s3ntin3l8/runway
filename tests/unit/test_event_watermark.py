from datetime import UTC, datetime

from scripts.sidecar_pkg.event_watermark import EventWatermark


def test_load_missing_returns_empty(tmp_path):
    w = EventWatermark(tmp_path / "wm.json")
    assert w.last_pushed("anthropic", "u@x") is None


def test_advance_and_persist(tmp_path):
    p = tmp_path / "wm.json"
    w = EventWatermark(p)
    ts = datetime(2026, 5, 8, 14, 0, tzinfo=UTC)
    w.advance("anthropic", "u@x", ts)
    w2 = EventWatermark(p)
    assert w2.last_pushed("anthropic", "u@x") == ts


def test_advance_only_moves_forward(tmp_path):
    w = EventWatermark(tmp_path / "wm.json")
    ts1 = datetime(2026, 5, 8, 14, 0, tzinfo=UTC)
    ts2 = datetime(2026, 5, 8, 13, 0, tzinfo=UTC)  # earlier
    w.advance("anthropic", "u@x", ts1)
    w.advance("anthropic", "u@x", ts2)
    assert w.last_pushed("anthropic", "u@x") == ts1


def test_corrupted_file_resets_to_empty(tmp_path):
    p = tmp_path / "wm.json"
    p.write_text("not json")
    w = EventWatermark(p)
    assert w.last_pushed("anthropic", "u@x") is None
