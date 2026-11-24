"""녹화 → 스텝 변환, 예약 시각 판정 (Qt·실제 입력 없음)."""
import time

from engine.model import new_macro, validate_macro
from gui.v2 import schedule as sch
from gui.v2.recorder import events_to_steps


def test_record_events_to_valid_steps():
    ev = [(0, "down", (100, 200, "left")), (0.05, "up", (100, 200, "left")),
          (0.1, "down", (100, 200, "left")), (0.15, "up", (100, 200, "left")),
          (1.0, "key", ("h", [])), (1.1, "key", ("i", [])), (1.2, "key", ("enter", [])),
          (2.0, "key", ("c", ["ctrl"])), (3.0, "down", (10, 10, "left")), (3.5, "up", (300, 10, "left")),
          (4.0, "down", (5, 5, "right")), (4.05, "up", (5, 5, "right"))]
    steps = events_to_steps(ev)
    types = [s["type"] for s in steps]
    assert types == ["click", "delay", "type_text", "key", "delay", "key", "delay", "drag", "delay", "click"]
    assert steps[0]["count"] == 2 and steps[2]["text"] == "hi" and steps[5]["keys"] == "ctrl+c"
    assert steps[-1]["button"] == "right"
    assert validate_macro(new_macro("녹화", steps)) == []


def test_schedule_due_every_and_daily():
    now = time.time()
    assert sch.due({"macro": "a", "mode": "every", "minutes": 1, "last": now - 61}, now)
    assert not sch.due({"macro": "a", "mode": "every", "minutes": 1, "last": now - 30}, now)
    hh = time.strftime("%H:%M", time.localtime(now))
    assert sch.due({"macro": "a", "mode": "daily", "time": hh, "last": 0}, now)
    assert not sch.due({"macro": "a", "mode": "daily", "time": hh, "last": now}, now)
    assert not sch.due({"macro": "a", "mode": "every", "minutes": 1, "last": 0, "on": False}, now)


def test_schedule_save_load(tmp_path):
    items = [{"macro": "m", "mode": "daily", "time": "07:30", "on": True, "last": 0}]
    sch.save(str(tmp_path), items)
    assert sch.load(str(tmp_path)) == items
